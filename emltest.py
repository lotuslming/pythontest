import os
import sys
import re
import traceback
from typing import List, Optional, Tuple
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser

from bs4 import BeautifulSoup

# ====== 配置：选择翻译实现 ======
# True 使用 Google Cloud Translation (官方)；False 使用 googletrans（非官方）
USE_GOOGLE_CLOUD = True

# 目标语言：简体中文
TARGET_LANG = "zh-CN"

# 每段翻译最大字符数，避免超限（Google 官方单次请求最大 30K 字节左右，这里保守一些）
MAX_CHARS_PER_CHUNK = 4000


def safe_str(s: Optional[str]) -> str:
    return s if isinstance(s, str) else (s.decode("utf-8", "ignore") if isinstance(s, bytes) else "")


def decode_mime_header(value: Optional[str]) -> str:
    """解码 RFC 2047/2231 头部（如 Subject、文件名等），并返回 str。"""
    if value is None:
        return ""
    try:
        dh = decode_header(value)
        parts = []
        for bytes_or_str, enc in dh:
            if isinstance(bytes_or_str, bytes):
                parts.append(bytes_or_str.decode(enc or "utf-8", errors="replace"))
            else:
                parts.append(bytes_or_str)
        return "".join(parts)
    except Exception:
        # 兜底
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value


def extract_text_from_html(html: str) -> str:
    """将 HTML 正文抽取为纯文本。"""
    soup = BeautifulSoup(html, "html.parser")
    # 去除脚本和样式
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # 规范空白
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def get_email_body(msg) -> str:
    """优先取 text/plain；若没有则从 text/html 提取纯文本；多段合并。"""
    plain_parts: List[str] = []
    html_parts: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            dispo = (part.get_content_disposition() or "").lower()
            if dispo == "attachment":
                continue  # 附件不当正文
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue

            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        # 非 multipart
        ctype = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            if payload is not None:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if ctype == "text/plain":
                    plain_parts.append(text)
                elif ctype == "text/html":
                    html_parts.append(text)
        except Exception:
            pass

    body = "\n\n".join(p.strip() for p in plain_parts if p and p.strip())
    if not body and html_parts:
        # 没有纯文本，用 HTML 提取
        html_texts = [extract_text_from_html(h) for h in html_parts]
        body = "\n\n".join(t for t in html_texts if t and t.strip())

    return body.strip()


def get_attachments_names(msg) -> List[str]:
    names = []
    for part in msg.walk():
        dispo = (part.get_content_disposition() or "").lower()
        if dispo == "attachment" or part.get_filename():
            fname = decode_mime_header(part.get_filename())
            if fname:
                names.append(fname)
    return names


# ====== 翻译实现 ======
class Translator:
    def __init__(self, target_lang: str):
        self.target_lang = target_lang
        if USE_GOOGLE_CLOUD:
            # 官方 SDK（v3）
            from google.cloud import translate
            self.client = translate.TranslationServiceClient()
            # 环境变量 GOOGLE_APPLICATION_CREDENTIALS 已配置凭据文件
            self.project_id = self._detect_project_id()
            # v3 API 需要位置，一般用 "global"
            self.location = "global"
            self.parent = f"projects/{self.project_id}/locations/{self.location}"
        else:
            from googletrans import Translator as GT
            self.client = GT()

    def _detect_project_id(self) -> str:
        # 优先从凭据里读；若失败可让用户手动填
        # 官方 SDK 会自动解析 GOOGLE_APPLICATION_CREDENTIALS，中含 project_id
        # 这里用一个轻量方式：尝试从环境变量读取
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
        if project_id:
            return project_id
        # 若为空，让用户也能通过备用环境变量设置
        env_pid = os.getenv("GCP_PROJECT_ID")
        if env_pid:
            return env_pid
        # 最后：提醒用户手动设置，避免运行期才报错
        # 这里返回一个占位符，真正调用会抛错并提示
        return "<YOUR_PROJECT_ID>"

    def translate_text(self, text: str) -> str:
        text = text or ""
        text = text.strip()
        if not text:
            return ""

        # 分片，尽量按段落切，避免句子被截断
        chunks = self._split_text(text, MAX_CHARS_PER_CHUNK)
        if USE_GOOGLE_CLOUD:
            translated_chunks = []
            for ch in chunks:
                # v3 API
                resp = self.client.translate_text(
                    request={
                        "parent": self.parent,
                        "contents": [ch],
                        "mime_type": "text/plain",
                        "target_language_code": self.target_lang,
                    }
                )
                translated_chunks.append(resp.translations[0].translated_text if resp.translations else "")
            return "\n".join(translated_chunks).strip()
        else:
            # googletrans 支持批量，但为稳妥逐段
            outs = []
            for ch in chunks:
                outs.append(self.client.translate(ch, dest=self.target_lang).text)
            return "\n".join(outs).strip()

    @staticmethod
    def _split_text(text: str, max_len: int) -> List[str]:
        if len(text) <= max_len:
            return [text]
        parts = []
        # 先按双换行分段
        paragraphs = re.split(r"\n{2,}", text)
        buf = ""
        for p in paragraphs:
            if not buf:
                candidate = p
            else:
                candidate = buf + "\n\n" + p
            if len(candidate) <= max_len:
                buf = candidate
            else:
                if buf:
                    parts.append(buf)
                # 如果单段也超长，再硬切
                if len(p) > max_len:
                    for i in range(0, len(p), max_len):
                        parts.append(p[i : i + max_len])
                    buf = ""
                else:
                    buf = p
        if buf:
            parts.append(buf)
        return parts


def format_output(
    eml_path: str,
    sender: str,
    recipients: str,
    date_str: str,
    subject_raw: str,
    subject_cn: str,
    body_raw: str,
    body_cn: str,
    attach_raw: List[str],
    attach_cn: List[str],
) -> str:
    lines = []
    lines.append(f"发件人: {sender}")
    lines.append(f"收件人: {recipients}")
    lines.append(f"时间: {date_str}")
    lines.append("")
    lines.append("邮件标题（原文）:")
    lines.append(subject_raw or "")
    lines.append("")
    lines.append("邮件标题（中文）:")
    lines.append(subject_cn or "")
    lines.append("\n" + "=" * 60 + "\n")
    lines.append("邮件正文（原文）:")
    lines.append(body_raw or "")
    lines.append("")
    lines.append("邮件正文（中文）:")
    lines.append(body_cn or "")
    lines.append("\n" + "=" * 60 + "\n")
    lines.append("邮件附件列表：")
    if attach_raw:
        for i, name in enumerate(attach_raw):
            cn = attach_cn[i] if i < len(attach_cn) else ""
            lines.append(f"- {name}  ——  {cn}")
    else:
        lines.append("- （无附件）")
    lines.append("\n" + "=" * 60 + "\n")
    lines.append(f"邮件原文件路径: {eml_path}")
    return "\n".join(lines).rstrip() + "\n"


def process_eml_file(eml_path: str, translator: Translator) -> Tuple[bool, Optional[str]]:
    try:
        with open(eml_path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)

        sender = decode_mime_header(msg.get("From"))
        recipients = decode_mime_header(msg.get("To"))
        date_str = safe_str(msg.get("Date"))
        subject_raw = decode_mime_header(msg.get("Subject"))

        body_raw = get_email_body(msg)
        attach_raw = get_attachments_names(msg)

        # 翻译：主题、正文、附件
        subject_cn = translator.translate_text(subject_raw) if subject_raw else ""
        body_cn = translator.translate_text(body_raw) if body_raw else ""
        attach_cn = [translator.translate_text(n) if n else "" for n in attach_raw]

        out_text = format_output(
            eml_path=eml_path,
            sender=sender,
            recipients=recipients,
            date_str=date_str,
            subject_raw=subject_raw,
            subject_cn=subject_cn,
            body_raw=body_raw,
            body_cn=body_cn,
            attach_raw=attach_raw,
            attach_cn=attach_cn,
        )

        # 输出到同目录，同名 .txt
        base, _ = os.path.splitext(eml_path)
        out_path = base + ".txt"
        with open(out_path, "w", encoding="utf-8") as fw:
            fw.write(out_text)

        return True, out_path
    except Exception as e:
        return False, f"{eml_path}: {e}\n{traceback.format_exc()}"


def walk_and_process(root_dir: str) -> None:
    translator = Translator(TARGET_LANG)
    total = 0
    ok = 0
    errors: List[str] = []

    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            if name.lower().endswith(".eml"):
                total += 1
                eml_path = os.path.join(dirpath, name)
                success, info = process_eml_file(eml_path, translator)
                if success:
                    ok += 1
                    print(f"[OK] {eml_path} -> {info}")
                else:
                    errors.append(info)
                    print(f"[ERR] {eml_path}")

    print("\n=== 汇总 ===")
    print(f"总计 .eml: {total}")
    print(f"成功生成: {ok}")
    print(f"失败: {len(errors)}")
    if errors:
        print("\n错误详情：")
        for e in errors:
            print("-" * 80)
            print(e)


def main():
    if len(sys.argv) < 2:
        print("用法: python eml_translate_to_cn.py <目录路径>")
        sys.exit(1)
    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"错误：{root} 不是有效的目录")
        sys.exit(1)
    walk_and_process(root)


if __name__ == "__main__":
    main()
