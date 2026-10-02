# -*- coding: utf-8 -*-
"""Validate the syntax layer against a manually reviewed CSV sample."""
import argparse
from pathlib import Path
import pandas as pd
from oracle_fix.OracleCompare.pipeline import compare_oracle_texts


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--output', default='syntax_validation_predictions.csv')
    args=ap.parse_args()
    df=pd.read_csv(args.csv, encoding='gb18030')
    rows=[]
    for _,r in df.iterrows():
        x=compare_oracle_texts(str(r['generated_oracle']), str(r['reference_oracle']), use_smt_fallback=False)
        rows.append({
            'predicted_match_level':x['match_level'],
            'requires_review':x['requires_review'],
            'automatic_match_level':x['automatic_match_level'],
            'num_generated':x['num_generated'],
            'num_reference':x['num_reference'],
            'unknown_generated':'|'.join(x['unknown_generated']),
            'unknown_reference':'|'.join(x['unknown_reference']),
        })
    out=pd.concat([df,pd.DataFrame(rows)],axis=1)
    out['prediction_correct']=out['predicted_match_level']==out['match_level']
    out.to_csv(args.output,index=False,encoding='utf-8-sig')
    print(f"agreement={out['prediction_correct'].mean():.2%} ({out['prediction_correct'].sum()}/{len(out)})")
    print(f"requires_review={out['requires_review'].sum()}/{len(out)}")
    print(f"written: {Path(args.output).resolve()}")

if __name__=='__main__':
    main()
