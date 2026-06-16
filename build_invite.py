import argparse
from invitation_engine import render_from_json

parser = argparse.ArgumentParser(description="Dijital davetiye HTML üretici")
parser.add_argument("--config", required=True, help="JSON config dosyası")
parser.add_argument("--template", default=None, help="Tema anahtarı: ilkbahar_cicek, yaz_lavanta, sonbahar_akcaagac, kis_kar, royal_rose, black_gold, botanik_ivory")
parser.add_argument("--out", default="dist", help="Çıktı klasörü")
parser.add_argument("--music", default=None, help="MP3/WAV/M4A müzik dosyası yolu")
args = parser.parse_args()

path = render_from_json(args.config, template_key=args.template, out_dir=args.out, music_path=args.music)
print(f"Davetiye hazır: {path}")
