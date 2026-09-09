import json
from pathlib import Path

from tools.video.seedance_ark import SeedanceArkVideo


ROOT = Path('/Users/yichen/Documents/Codex/2026-08-31/x20-x20-x20-x-x20-x20')
OUT_DIR = ROOT / 'outputs/short-video-sample-652353160506'
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_VIDEO = OUT_DIR / 'new-causal-05s-v2_652353160506_seedance25.mp4'
PROMPT_FILE = OUT_DIR / 'shot-01-water-causality-prompt-v2-zh-en.md'
prompt = PROMPT_FILE.read_text(encoding='utf-8')

result = SeedanceArkVideo().execute({
    'task_action': 'generate',
    'operation': 'reference_to_video',
    'model_variant': '2.5',
    'duration': 5,
    'aspect_ratio': '9:16',
    'resolution': '720p',
    'generate_audio': True,
    'watermark': False,
    'return_last_frame': True,
    'custom_price_cny_per_million_tokens': 46,
    'prompt': prompt,
    'reference_image_paths': [
        str(ROOT / 'outputs/short-video-sample-652353160506/references/product-anchor-clean-652-compatible-padded.png'),
    ],
    'output_path': str(OUT_VIDEO),
})

record = {
    'success': result.success,
    'error': result.error,
    'data': result.data,
    'artifacts': result.artifacts,
    'cost_usd': result.cost_usd,
    'duration_seconds': result.duration_seconds,
    'seed': result.seed,
    'model': result.model,
}
(OUT_DIR / 'new-causal-05s-generation.json').write_text(
    json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8'
)
print(json.dumps(record, ensure_ascii=False, indent=2))
