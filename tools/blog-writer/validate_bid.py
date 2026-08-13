import os
import sys
import json
import re

def load_bid_system(method_path):
    bid_system_path = os.path.join(method_path, 'references', 'bid-system.md')
    if not os.path.exists(bid_system_path):
        print(f'❌ bid-system.md 不存在: {bid_system_path}')
        return None
    
    with open(bid_system_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    valid_enums = {}
    current_section = None
    
    for line in content.split('\n'):
        if line.startswith('## '):
            current_section = line[3:].strip()
        elif line.strip() and current_section:
            match = re.match(r'^([A-Za-z]{2})\((\d+)\):', line)
            if match:
                layer = match.group(1)
                count = int(match.group(2))
                valid_enums[layer] = []
                parts = line.split(':')[1].strip()
                for part in parts.split():
                    if part.isalnum():
                        valid_enums[layer].append(part)
    
    return valid_enums

def validate_bid(instance_dir, method_path):
    bid_path = os.path.join(instance_dir, '000 BID.json')
    if not os.path.exists(bid_path):
        print('❌ 000 BID.json 不存在')
        return False
    
    with open(bid_path, 'r', encoding='utf-8') as f:
        try:
            bid = json.load(f)
        except json.JSONDecodeError as e:
            print(f'❌ JSON解析错误: {e}')
            return False
    
    errors = []
    
    if 'bid' not in bid:
        errors.append('缺少 bid 字段')
        return False
    
    bid_data = bid['bid']
    
    required_layers = ['core', 'web', 'seo', 'geo', 'cl']
    for layer in required_layers:
        if layer not in bid_data:
            errors.append(f'缺少 {layer} 层')
            continue
        
        layer_data = bid_data[layer]
        if not isinstance(layer_data, dict):
            errors.append(f'{layer} 层格式错误')
            continue
    
    if 'core' in bid_data:
        core_fields = ['at', 'th', 'pi', 'ct', 'pv', 'pr', 'al', 'dp', 'tm', 'fm', 'tn', 'so', 'ev']
        for field in core_fields:
            if field not in bid_data['core'] or not bid_data['core'][field]:
                errors.append(f'CO层缺少或为空: {field}')
    
    if 'web' in bid_data:
        web_fields = ['obj', 'uc', 'js', 'cta', 'ci', 'pm', 'rk']
        for field in web_fields:
            if field not in bid_data['web'] or not bid_data['web'][field]:
                errors.append(f'WB层缺少或为空: {field}')
    
    if 'seo' in bid_data:
        seo_fields = ['si', 'qs', 'kl', 'kc', 'sf', 'sc', 'ic']
        for field in seo_fields:
            if field not in bid_data['seo'] or not bid_data['seo'][field]:
                errors.append(f'SE层缺少或为空: {field}')
    
    if 'geo' in bid_data:
        geo_fields = ['gi', 'gs', 'gf', 'gn', 'gc']
        for field in geo_fields:
            if field not in bid_data['geo'] or not bid_data['geo'][field]:
                errors.append(f'GE层缺少或为空: {field}')
    
    if 'cl' in bid_data:
        cl_fields = ['pi', 'sub', 'cr', 'il', 'lt', 'pf']
        for field in cl_fields:
            if field not in bid_data['cl']:
                errors.append(f'CL层缺少字段: {field}')
    
    if 'lo' not in bid_data or not bid_data['lo']:
        errors.append('LO层缺少或为空')
    
    if 'st' not in bid_data or not bid_data['st']:
        errors.append('ST层缺少或为空')
    
    if 'summary' in bid:
        summary = bid['summary']
        if not summary.get('title'):
            errors.append('summary.title 为空')
        if not summary.get('slug'):
            errors.append('summary.slug 为空')
        if not summary.get('keyword'):
            errors.append('summary.keyword 为空')
        
        if summary.get('meta_description') and summary.get('keyword'):
            kw = summary['keyword'].lower()
            md = summary['meta_description'].lower()
            if kw not in md:
                errors.append('meta_description 不包含关键词')
    
    if errors:
        print('❌ BID校验失败:')
        for err in errors:
            print(f'  - {err}')
        return False
    
    print('✅ BID校验通过')
    return True

def main():
    parser = argparse.ArgumentParser(description='校验BID标识')
    parser.add_argument('--out-dir', required=True, help='实例目录')
    parser.add_argument('--method-path', default='.', help='方法母版路径')
    
    args = parser.parse_args()
    
    if validate_bid(args.out_dir, args.method_path):
        bid_path = os.path.join(args.out_dir, '000 BID.json')
        with open(bid_path, 'r', encoding='utf-8') as f:
            bid = json.load(f)
        
        bid['validation'] = {
            'passed': True,
            'issues': []
        }
        
        with open(bid_path, 'w', encoding='utf-8') as f:
            json.dump(bid, f, indent=2, ensure_ascii=False)
        
        print('✅ validation.passed 已设为 true')
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
