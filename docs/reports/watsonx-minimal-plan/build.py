import base64, re, pathlib, sys
root = pathlib.Path(__file__).parent
src = (root / 'report.src.html').read_text(encoding='utf-8')
def rep(m):
    p = root / 'img' / f'{m.group(1)}.webp'
    return 'data:image/webp;base64,' + base64.b64encode(p.read_bytes()).decode()
out = re.sub(r'\{\{IMG:([a-z_]+)\}\}', rep, src)
assert '{{IMG:' not in out
(root / 'watsonx-minimal-plan.html').write_text(out, encoding='utf-8')
print('built', len(out)//1024, 'KB')
