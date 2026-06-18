from pathlib import Path
import collections

md_leveling = Path('output/二等水准观测手簿.md').read_text(encoding='utf-8')
md_traverse = Path('output/一级导线观测手簿.md').read_text(encoding='utf-8')

print('=' * 60)
print('一、二等水准观测手簿分析')
print('=' * 60)

lines = md_leveling.splitlines()
in_s1 = False
rows = []
for line in lines:
    if '## 测段 S1 观测记录' in line:
        in_s1 = True
        continue
    if in_s1 and line.startswith('##'):
        break
    if in_s1 and line.strip().startswith('|') and '站号' not in line and '---' not in line:
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) >= 20:
            rows.append(cells)

print(f'测站数: {len(rows)}')
back_diffs = [r[15] for r in rows]
fore_diffs = [r[16] for r in rows]
print(f'基辅差后唯一值: {sorted(set(back_diffs))}')
print(f'基辅差前唯一值: {sorted(set(fore_diffs))}')

for label, idx_basic, idx_aux in [('后视', 5, 6), ('前视', 9, 10)]:
    diffs = [float(r[idx_aux]) - float(r[idx_basic]) for r in rows]
    print(f'{label} 基辅读数差 (aux-basic) 范围: [{min(diffs):.4f}, {max(diffs):.4f}] m')

h_basic = [float(r[17]) for r in rows]
h_aux = [float(r[18]) for r in rows]
h_mean = [float(r[19]) for r in rows]
print(f'h基=h辅=h中的站数: {sum(1 for a,b,c in zip(h_basic,h_aux,h_mean) if a==b==c)}/{len(rows)}')
print(f'h基-h辅 max: {max(abs(a-b) for a,b in zip(h_basic,h_aux))*1000:.4f} mm')

sight_back = [float(r[11]) for r in rows]
sight_fore = [float(r[12]) for r in rows]
print(f'后视距范围: [{min(sight_back):.1f}, {max(sight_back):.1f}] m')
print(f'前视距范围: [{min(sight_fore):.1f}, {max(sight_fore):.1f}] m')


print()
print('=' * 60)
print('二、一级导线观测手簿分析')
print('=' * 60)

lines = md_traverse.splitlines()
in_comp = False
comp_lines = []
for line in lines:
    if '## 成果计算' in line:
        in_comp = True
        continue
    if in_comp and line.startswith('##'):
        break
    if in_comp and line.strip().startswith('|'):
        comp_lines.append(line)

rows = []
for line in comp_lines[2:]:
    cells = [c.strip() for c in line.strip().strip('|').split('|')]
    if len(cells) >= 14 and cells[0] and not cells[0].startswith('---'):
        rows.append(cells)

point_rows = [r for r in rows if r[0] and not r[0].startswith('→')]
edge_rows = [r for r in rows if r[0].startswith('→')]
print(f'点行数: {len(point_rows)}, 边行数: {len(edge_rows)}')

v_beta = [float(r[2]) for r in rows if r[2]]
print(f'v_β 值: {v_beta}')
print(f'v_β 唯一值数: {len(set(v_beta))}')

v_x = [float(r[8]) for r in edge_rows if r[8]]
v_y = [float(r[9]) for r in edge_rows if r[9]]
print(f'v_x 唯一值数: {len(set(v_x))}, 值: {sorted(set(v_x))}')
print(f'v_y 唯一值数: {len(set(v_y))}, 值: {sorted(set(v_y))}')

# 水平角观测表
in_angle = False
angle_rows = []
for line in lines:
    if '## 水平角观测' in line:
        in_angle = True
        continue
    if in_angle and line.startswith('##'):
        break
    if in_angle and line.strip().startswith('|') and '测站' not in line and '---' not in line:
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) >= 8:
            angle_rows.append(cells)

print(f'水平角观测行数: {len(angle_rows)}')
two_c = [r[4] for r in angle_rows if r[4]]
print(f'2C 唯一值数: {len(set(two_c))}')

# 距离观测表
in_dist = False
dist_rows = []
for line in lines:
    if '## 距离观测' in line:
        in_dist = True
        continue
    if in_dist and line.startswith('##'):
        break
    if in_dist and line.strip().startswith('|') and '边名' not in line and '---' not in line:
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) >= 8:
            dist_rows.append(cells)

print(f'距离观测行数: {len(dist_rows)}')
read_diffs = [r[5] for r in dist_rows if r[5]]
print(f'读数差列唯一值数: {len(set(read_diffs))}')

# 检查水平角观测中同一测站同一目标跨测回方向值差异
station_set_dirs = collections.defaultdict(list)
for r in angle_rows:
    station = r[0]
    target = r[2]
    face = r[3]
    dir_val = r[5] if face == 'L' else r[6]
    if dir_val and dir_val != '-':
        station_set_dirs[(station, target, face)].append(dir_val)

multi = [(k, v) for k, v in station_set_dirs.items() if len(v) > 1]
print(f'同站同目标同盘位跨测回方向值数量>1的: {len(multi)}')
