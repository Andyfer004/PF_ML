"""Compara candidatos con referencias identificadas y confirmadas por el equipo."""
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.ocr_evaluation import evaluate
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=ROOT/'output/ocr_completo.json')
    parser.add_argument('--references',type=Path,required=True)
    args=parser.parse_args()
    with args.references.open(newline='',encoding='utf-8') as stream:
        refs=json.load(stream) if args.references.suffix=='.json' else list(csv.DictReader(stream))
    print(json.dumps(evaluate(json.loads(args.report.read_text()),refs),ensure_ascii=False,indent=2))
