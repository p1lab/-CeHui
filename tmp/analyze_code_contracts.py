"""分析代码中硬编码与配置文件的契约关系."""
from pathlib import Path
import json
import re
from collections import defaultdict

ROOT = Path('D:/Data/Documents/模拟观测数据CeHui')
SRC = ROOT / 'src'
CONFIG = ROOT / 'config'


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def collect_leaf_values(obj, prefix='', result=None):
    """递归收集 JSON 中的所有叶子数值和字符串."""
    if result is None:
        result = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f'{prefix}.{k}' if prefix else k
            collect_leaf_values(v, new_prefix, result)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect_leaf_values(v, f'{prefix}[{i}]', result)
    elif isinstance(obj, (int, float, str)):
        result[prefix] = obj
    return result


def find_in_source(value):
    """在源码中搜索给定的值,返回匹配列表."""
    matches = []
    # 转义正则特殊字符
    if isinstance(value, str):
        pattern = re.escape(value)
    elif isinstance(value, float):
        # 浮点数可能以不同精度出现
        pattern = re.escape(str(value))
        # 也尝试无小数点形式
        if value == int(value):
            pattern = f'({pattern}|{int(value)}\\.0*)'
    else:
        pattern = re.escape(str(value))

    for py_file in SRC.rglob('*.py'):
        text = py_file.read_text(encoding='utf-8')
        for i, line in enumerate(text.splitlines(), 1):
            # 忽略注释行中的匹配
            code_part = line.split('#')[0]
            if re.search(pattern, code_part):
                matches.append((py_file, i, line.strip()))
    return matches


def main():
    config_files = list(CONFIG.glob('*.json'))
    print('=' * 70)
    print('代码-配置契约调研报告')
    print('=' * 70)

    all_config_values = {}
    for cf in config_files:
        data = load_json(cf)
        leaves = collect_leaf_values(data)
        all_config_values[cf.name] = leaves

    # 1. 统计源码中是否引用了配置文件
    print('\n## 1. 配置文件引用情况')
    config_refs = defaultdict(list)
    for py_file in SRC.rglob('*.py'):
        text = py_file.read_text(encoding='utf-8')
        for cf_name in [f.name for f in config_files]:
            if cf_name in text:
                config_refs[cf_name].append(py_file)
    for cf_name in [f.name for f in config_files]:
        refs = config_refs[cf_name]
        if refs:
            print(f'{cf_name}: 在 {len(refs)} 个文件中被提及')
            for rf in refs:
                print(f'  - {rf.relative_to(ROOT)}')
        else:
            print(f'{cf_name}: 未被任何源码文件提及')

    # 2. 检查哪些 config 叶子值在源码中出现过
    print('\n## 2. Config 中数值/字符串在源码中的出现情况')
    used_in_code = {}
    unused_in_code = {}
    for cf_name, leaves in all_config_values.items():
        used = []
        unused = []
        for key, value in leaves.items():
            # 跳过 _meta 等描述性字段
            if key.startswith('_') or 'note' in key.lower() or 'description' in key.lower():
                continue
            matches = find_in_source(value)
            if matches:
                used.append((key, value, matches[:3]))  # 只保留前3个匹配
            else:
                unused.append((key, value))
        used_in_code[cf_name] = used
        unused_in_code[cf_name] = unused

    for cf_name in [f.name for f in config_files]:
        used = used_in_code[cf_name]
        unused = unused_in_code[cf_name]
        print(f'\n### {cf_name}')
        print(f'  在源码中有匹配的配置项: {len(used)}')
        print(f'  在源码中无匹配的配置项: {len(unused)}')
        if unused:
            print('  未匹配项样例:')
            for key, value in unused[:15]:
                print(f'    - {key} = {value}')
            if len(unused) > 15:
                print(f'    ... 等共 {len(unused)} 项')

    # 3. 寻找源码中的硬编码数字/字符串, 判断是否与 config 重复
    print('\n## 3. 源码中疑似硬编码的配置相关常量')
    hardcoded_candidates = []
    for py_file in SRC.rglob('*.py'):
        text = py_file.read_text(encoding='utf-8')
        for i, line in enumerate(text.splitlines(), 1):
            code_part = line.split('#')[0]
            # 匹配 dict 中的数字/字符串值, 支持行尾逗号/右括号
            if re.search(r'["\']\w+["\']\s*:\s*[\-]?\d+\.?\d*\s*[,\]]?', code_part):
                # 过滤掉纯索引等, 保留配置相关字典
                if any(kw in code_part for kw in ['_LEVELS', '_LIMITS', '_PARAMS', '_SPECS', '_COEFF']):
                    hardcoded_candidates.append((py_file, i, line.strip()))
    print(f'发现 {len(hardcoded_candidates)} 处字典中的硬编码数值')
    for pf, ln, line in hardcoded_candidates[:40]:
        print(f'  {pf.relative_to(ROOT)}:{ln}: {line}')

    # 4. 检查源码中是否存在 config_path 参数但不读取 config 的函数
    print('\n## 4. 声明 config_path 参数但未实际读取配置文件的函数')
    config_path_funcs = []
    for py_file in SRC.rglob('*.py'):
        text = py_file.read_text(encoding='utf-8')
        # 找 function def 中包含 config_path 的 (支持多行)
        for match in re.finditer(r'def\s+(\w+)\s*\(', text):
            func_name = match.group(1)
            start = match.start()
            # 找匹配的右括号
            paren_count = 0
            end = start
            for j, ch in enumerate(text[start:], start):
                if ch == '(':
                    paren_count += 1
                elif ch == ')':
                    paren_count -= 1
                    if paren_count == 0:
                        end = j
                        break
            sig = text[start:end+1]
            if 'config_path' in sig:
                # 函数体从 end+1 到下一个同缩进 def 或文件结束
                body_start = end + 1
                body_end = len(text)
                # 简单取函数体前 1000 字符
                body = text[body_start:body_start+1000]
                if 'open(' not in body and 'json.load' not in body and 'read_text' not in body:
                    config_path_funcs.append((py_file, func_name, body_start))
    for pf, fn, ln in config_path_funcs:
        print(f'  {pf.relative_to(ROOT)}:{fn}(config_path=...) 未实际读取配置')


if __name__ == '__main__':
    main()
