import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path('/Users/yichen/Documents/Codex/2026-08-31/x20-x20-x20-x-x20-x20')
VIDEO_DIR = ROOT / 'outputs/short-video-sample-652353160506'
INPUT = VIDEO_DIR / 'full-20s-v3_652353160506_seedance25.mp4'
OUTPUT = VIDEO_DIR / 'full-20s-v3-final_652353160506_seedance25.mp4'
WIDTH, HEIGHT, FPS = 720, 1280, 24
FONT_PATH = '/System/Library/Fonts/STHeiti Medium.ttc'


def font(size: int):
    return ImageFont.truetype(FONT_PATH, size=size, index=0)


def caption_for_time(t: float) -> str:
    if t < 2:
        return '写作业时，水杯碰倒了？'
    if t < 5:
        return '透明桌垫，木纹仍看得见'
    if t < 9:
        return '清水场景演示｜擦拭过程连续可见'
    if t < 12:
        return '掀角检查｜桌面状态以现场为准'
    if t < 16:
        return '给学习桌多一层保护，写作业更从容'
    return '量长×量宽×看桌角，透明斜边 2.0mm 先确认再选'


def draw_caption(frame: bytes, t: float) -> bytes:
    image = Image.frombytes('RGB', (WIDTH, HEIGHT), frame)
    draw = ImageDraw.Draw(image, 'RGBA')
    top_text = caption_for_time(t)
    top_font = font(34 if len(top_text) < 18 else 27)
    top_box = (28, 50, WIDTH - 28, 132)
    draw.rounded_rectangle(top_box, radius=20, fill=(20, 20, 20, 145))
    draw.text((52, 67), top_text, font=top_font, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 180))

    bottom_text = 'AI场景演示｜清水条件，实际效果以现场实测为准'
    bottom_font = font(23)
    bottom_box = (28, HEIGHT - 105, WIDTH - 28, HEIGHT - 38)
    draw.rounded_rectangle(bottom_box, radius=18, fill=(20, 20, 20, 150))
    draw.text((48, HEIGHT - 89), bottom_text, font=bottom_font, fill=(245, 245, 245, 255), stroke_width=1, stroke_fill=(0, 0, 0, 180))
    return image.tobytes()


def main():
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height,r_frame_rate', '-of', 'default=nw=1', str(INPUT)],
        check=True, capture_output=True, text=True,
    )
    if 'width=720' not in probe.stdout or 'height=1280' not in probe.stdout:
        raise RuntimeError(f'Unexpected input dimensions: {probe.stdout}')

    decoder = subprocess.Popen(
        ['ffmpeg', '-loglevel', 'error', '-i', str(INPUT), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        stdout=subprocess.PIPE,
    )
    encoder = subprocess.Popen(
        [
            'ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-', '-i', str(INPUT),
            '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'libx264', '-preset', 'medium',
            '-crf', '18', '-c:a', 'copy', '-movflags', '+faststart', str(OUTPUT),
        ],
        stdin=subprocess.PIPE,
    )
    frame_bytes = WIDTH * HEIGHT * 3
    index = 0
    while True:
        raw = decoder.stdout.read(frame_bytes)
        if len(raw) != frame_bytes:
            break
        encoder.stdin.write(draw_caption(raw, index / FPS))
        index += 1
    decoder.stdout.close()
    decoder.wait()
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise RuntimeError('ffmpeg encoder failed')
    print(OUTPUT)


if __name__ == '__main__':
    main()
