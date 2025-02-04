import os
from mutagen import File
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
import numpy as np
import soundfile as sf

def calculate_snr(audio_data):
    """计算音频数据的信噪比"""
    # 计算信号的均方值
    signal_rms = np.mean(np.square(audio_data))
    
    # 估计噪声（假设最安静的 10% 的帧为噪声）
    frame_size = 2048
    frames = np.array_split(audio_data, len(audio_data) // frame_size)
    frame_rms = np.array([np.sqrt(np.mean(np.square(frame))) for frame in frames])
    noise_rms = np.mean(np.square(np.percentile(frame_rms, 10)))
    
    # 避免除以零
    if noise_rms == 0:
        return 100.0
    
    # 计算 SNR（以分贝为单位）
    snr_db = 10 * np.log10(signal_rms / noise_rms)
    return round(snr_db, 2)

def get_audio_info(file_path):
    try:
        # 使用mutagen读取音频文件
        audio = File(file_path)
        
        if audio is None:
            print(f"不支持的文件格式: {file_path}")
            return None
            
        # 使用soundfile读取音频数据计算SNR
        try:
            audio_data, sr = sf.read(file_path)
            # 如果是立体声，转换为单声道
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
            snr = calculate_snr(audio_data)
        except Exception as e:
            print(f"计算SNR时出错: {str(e)}")
            snr = 0
            
        print(snr)
        # 获取基本信息
        duration = audio.info.length  # 时长（秒）
        
        # 获取比特率
        if hasattr(audio.info, 'bitrate'):
            bitrate = audio.info.bitrate
        else:
            bitrate = audio.info.sample_rate * audio.info.bits_per_sample * audio.info.channels
            
        # 获取采样精度
        sample_width = getattr(audio.info, 'bits_per_sample', 16)  # 默认16位
        
        return {
            'path': file_path,
            'duration': round(duration, 2),
            'bitrate': bitrate,
            'snr': snr,
            'sample_width': sample_width
        }
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {str(e)}")
        return None

# main函数保持不变
def main():
    # 获取用户输入的目录
    directory = input("请输入要分析的目录路径: ").strip()
    
    # 检查目录是否存在
    if not os.path.exists(directory):
        print("目录不存在！")
        return
    
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(current_dir, "output.txt")
    
    # 支持的音频格式
    audio_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.wma')
    
    # 打开输出文件
    with open(output_file, 'w', encoding='utf-8') as f:
        # 写入表头
        f.write("文件路径&&时长(秒)&&码率(bps)&&信噪比(dB)&&采样精度(bit)\n")
        
        # 遍历目录
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.lower().endswith(audio_extensions):
                    file_path = os.path.join(root, file)
                    info = get_audio_info(file_path)
                    
                    if info:
                        # 写入文件信息
                        line = f"{info['path']}&&{info['duration']}&&{info['bitrate']}&&{info['snr']}&&{info['sample_width']}\n"
                        f.write(line)
    
    print(f"分析完成！结果已保存到: {output_file}")

if __name__ == "__main__":
    main()