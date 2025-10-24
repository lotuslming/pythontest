import os
import sys
import json
import math
import time
import argparse
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np
import faiss
from rich import print
from rich.table import Table
from rich.console import Console

# ============ 配置区域 ============
EMBED_MODEL = "text-embedding-3-small"   # 1536维，性价比高
CHAT_MODEL  = "gpt-4o-mini"              # 便宜快速，够用
CHUNK_SIZE  = 1200                       # 每段最大字符（中文等宽估算）
CHUNK_OVERLAP = 200                      # 块间重叠，保证语义连续
EMBED_BATCH = 96                         # 嵌入批大小
TOP_K       = 6                          # 检索返回块数
MAX_CONTEXT_CHARS = 12000                # 传给模型的总上下文字数上限
# =================================

# -------- OpenAI 官方 SDK（>=2024）--------
try:
    from openai import OpenAI
except Exception:
    # 旧版本包名为 openai；若用户装的是旧包，也尽量兼容
    raise SystemExit("请先安装 `pip install openai` (>=1.0)")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def file_sha1(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def normalize(v: np.ndarray) -> np.ndarray:
    # 余弦相似度：先单位化，FAISS 用内积即为 cos
    norms = np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    return v / norms

def embed_texts(texts: List[str]) -> np.ndarray:
    """调用 OpenAI 嵌入 API，批量生成向量"""
    vecs = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i+EMBED_BATCH]
        resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
        vecs.extend([d.embedding for d in resp.data])
        # 轻微休眠，友好限流
        time.sleep(0.05)
    arr = np.array(vecs, dtype="float32")
    return normalize(arr)

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        # 尽量在句号/换行处断开
        cut = end
        for sep in ["\n\n", "\n", "。", "！", "？", ".", "!", "?"]:
            pos = text.rfind(sep, start, end)
            if pos != -1 and pos > start + size * 0.6:
                cut = pos + len(sep)
                break
        chunk = text[start:cut]
        chunks.append(chunk.strip())
        start = max(cut - overlap, start + 1)
    # 去空
    return [c for c in chunks if c]

def load_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def build_index_from_folder(src_dir: Path, kb_dir: Path):
    ensure_dir(kb_dir)
    index_path = kb_dir / "index.faiss"
    meta_path  = kb_dir / "meta.jsonl"
    info_path  = kb_dir / "kb_info.json"

    texts, metas = [], []
    console = Console()

    # 遍历 txt（你上一脚本生成的 .txt 摘要）
    files = sorted([p for p in src_dir.rglob("*.txt") if p.is_file()])
    if not files:
        raise SystemExit(f"在 {src_dir} 未找到 .txt 文件")

    with console.status("[bold green]正在切分与收集文本..."):
        for f in files:
            raw = load_txt(f)
            # 用文件名作为标题，首行可能也含关键信息
            title = f.stem
            # 合并：标题 + 正文
            content = f"# {title}\n\n{raw}"
            chunks = chunk_text(content)
            for idx, ck in enumerate(chunks):
                texts.append(ck)
                metas.append({
                    "id": f"{file_sha1(f)}-{idx}",
                    "file": str(f),
                    "title": title,
                    "chunk_index": idx,
                })

    with console.status("[bold green]正在计算嵌入向量..."):
        emb = embed_texts(texts)  # (N, D)
        dim = emb.shape[1]

    # FAISS 索引（内积 = 余弦）
    index = faiss.IndexFlatIP(dim)
    index.add(emb)

    faiss.write_index(index, str(index_path))
    # 元信息写 jsonl
    with meta_path.open("w", encoding="utf-8") as fw:
        for m, t in zip(metas, texts):
            rec = {"meta": m, "text": t}
            fw.write(json.dumps(rec, ensure_ascii=False) + "\n")

    kb_info = {
        "dim": dim,
        "count": len(texts),
        "built_from": str(src_dir.resolve()),
        "embed_model": EMBED_MODEL,
    }
    info_path.write_text(json.dumps(kb_info, ensure_ascii=False, indent=2), encoding="utf-8")

    table = Table(title="知识库构建完成")
    table.add_column("条目数", justify="right")
    table.add_column("嵌入维度", justify="right")
    table.add_row(str(len(texts)), str(dim))
    print(table)
    print(f"[bold]索引文件：[/] {index_path}")
    print(f"[bold]元信息：[/] {meta_path}")

def load_kb(kb_dir: Path):
    index = faiss.read_index(str(kb_dir / "index.faiss"))
    metas = []
    texts = []
    with (kb_dir / "meta.jsonl").open("r", encoding="utf-8") as fr:
        for line in fr:
            rec = json.loads(line)
            metas.append(rec["meta"])
            texts.append(rec["text"])
    return index, metas, texts

def search_kb(kb_dir: Path, query: str, top_k=TOP_K) -> List[Dict]:
    index, metas, texts = load_kb(kb_dir)
    qv = embed_texts([query])  # (1, D)
    scores, idxs = index.search(qv, top_k)
    idxs = idxs[0].tolist()
    scores = scores[0].tolist()

    hits = []
    for i, sc in zip(idxs, scores):
        if i == -1:
            continue
        hit = {
            "score": float(sc),
            "text": texts[i],
            "meta": metas[i],
        }
        hits.append(hit)
    return hits

def build_context(hits: List[Dict], max_chars=MAX_CONTEXT_CHARS) -> Tuple[str, List[Dict]]:
    picked, total = [], 0
    for h in hits:
        t = h["text"]
        if total + len(t) > max_chars:
            break
        picked.append(h)
        total += len(t)
    blocks = []
    for i, h in enumerate(picked, 1):
        src = Path(h["meta"]["file"]).name
        blocks.append(f"[{i}] 来源: {src}  (片段#{h['meta']['chunk_index']})\n{tidy(h['text'])}")
    return "\n\n".join(blocks), picked

def tidy(s: str) -> str:
    return s.strip().replace("\r\n", "\n")

def chat_with_context(query: str, context: str) -> str:
    """调用对话模型进行 RAG 回答"""
    sys_prompt = (
        "你是严谨的中文知识助手。请仅依据给定【资料片段】回答；"
        "若片段不足以回答，请明确说明“资料不足”。回答要简洁、条理清晰。"
    )
    user_prompt = (
        f"问题：{query}\n\n"
        f"【资料片段】（可能有多段）\n{context}\n\n"
        "请基于以上片段回答。如果引用具体事实，请在句末用 [片段编号] 标注。"
    )
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

def ask(kb_dir: Path, query: str):
    hits = search_kb(kb_dir, query, TOP_K)
    context, picked = build_context(hits, MAX_CONTEXT_CHARS)
    answer = chat_with_context(query, context)

    print("\n[bold]答案：[/]")
    print(answer)
    print("\n[bold]参考片段：[/]")
    tab = Table(show_header=True, header_style="bold")
    tab.add_column("#", justify="right")
    tab.add_column("文件")
    tab.add_column("相似度")
    for i, h in enumerate(picked, 1):
        tab.add_row(str(i), Path(h["meta"]["file"]).name, f"{h['score']:.3f}")
    print(tab)

def summarize_corpus(kb_dir: Path, goal: str, max_docs=24):
    """对整个知识库做主题总结/报告（Map-Reduce）"""
    _, metas, texts = load_kb(kb_dir)
    # 取前 max_docs 个块做初步小结，再归纳
    chunks = texts[:max_docs]
    summaries = []
    for i in range(0, len(chunks), 8):
        batch = chunks[i:i+8]
        prompt = (
            "你是中文摘要器。请把以下多段资料概括成要点列表，保留关键信息、数字、时间和结论：\n\n"
            + "\n\n---\n\n".join(batch)
        )
        r = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "system", "content": "输出中文。"},
                      {"role": "user", "content": prompt}],
            temperature=0.2,
        )
        summaries.append(r.choices[0].message.content.strip())

    # 汇总
    final_prompt = (
        f"目标：{goal}\n\n以下是多份小结，请综合成结构化总结（含概要、关键要点、风险/结论/待办）：\n\n"
        + "\n\n====\n\n".join(summaries)
    )
    r2 = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "system", "content": "输出中文，结构清晰。"},
                  {"role": "user", "content": final_prompt}],
        temperature=0.2,
    )
    print(r2.choices[0].message.content.strip())

def main():
    ap = argparse.ArgumentParser(description="中文TXT知识库 + RAG 问答/总结")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_idx = sub.add_parser("index", help="从 TXT 目录构建/重建知识库")
    ap_idx.add_argument("src_dir", type=str, help="包含 .txt 的目录（会递归扫描）")
    ap_idx.add_argument("kb_dir", type=str, help="保存索引的目录")

    ap_ask = sub.add_parser("ask", help="对知识库提出问题（RAG）")
    ap_ask.add_argument("kb_dir", type=str, help="索引目录")
    ap_ask.add_argument("query", type=str, help="你的问题")

    ap_sum = sub.add_parser("summarize", help="对知识库生成主题总结")
    ap_sum.add_argument("kb_dir", type=str, help="索引目录")
    ap_sum.add_argument("--goal", type=str, default="生成高层中文总结",
                        help="总结目标/用途描述")
    args = ap.parse_args()

    cmd = args.cmd
    if cmd == "index":
        build_index_from_folder(Path(args.src_dir), Path(args.kb_dir))
    elif cmd == "ask":
        ask(Path(args.kb_dir), args.query)
    elif cmd == "summarize":
        summarize_corpus(Path(args.kb_dir), args.goal)
    else:
        ap.print_help()

if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("未检测到 OPENAI_API_KEY 环境变量。请先导出你的 API Key。")
    main()
