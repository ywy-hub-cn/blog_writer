import os
import sys
import json
import re
import argparse

def validate_content(instance_dir):
    draft_path = os.path.join(instance_dir, '004 正文.md')
    bid_path = os.path.join(instance_dir, '000 BID.json')
    
    if not os.path.exists(draft_path):
        print('❌ 004 正文.md 不存在')
        return False
    
    with open(draft_path, 'r', encoding='utf-8') as f:
        body = f.read()
    
    if not body.strip():
        print('❌ 正文内容为空')
        return False
    
    errors = []
    
    h2_count = len(re.findall(r'^## ', body, re.MULTILINE))
    if h2_count < 4:
        errors.append(f'H2数量不足: {h2_count} < 4')
    
    if 'FAQ' not in body and len(re.findall(r'\?\n', body)) < 3:
        errors.append('缺少FAQ模块')
    
    if '## References' not in body:
        errors.append('缺少 ## References 节')
    else:
        ref_section = body[body.find('## References'):]
        refs = re.findall(r'\[[^\]]+\]\(https?://[^)]+\)', ref_section)
        if len(refs) < 2:
            errors.append(f'References数量不足: {len(refs)} < 2')
        
        for phrase in ['industry knowledge', 'research reports', 'industry research']:
            if phrase.lower() in ref_section.lower():
                errors.append(f'References含笼统概括: "{phrase}"')
    
    if os.path.exists(bid_path):
        with open(bid_path, 'r', encoding='utf-8') as f:
            bid = json.load(f)
        kw = bid.get('summary', {}).get('keyword', '').lower()
        
        if kw:
            first_100 = ' '.join(body.split()[:100]).lower()
            if kw not in first_100:
                errors.append(f'关键词 "{kw}" 未出现在正文前100词内')
            
            exact_count = body.lower().count(kw)
            if exact_count < 3:
                errors.append(f'关键词 "{kw}" 出现次数不足: {exact_count} < 3')
    
    html_tags = re.findall(r'<[a-z]+[^>]*>', body)
    if html_tags:
        errors.append(f'正文中发现HTML标签残留: {html_tags[:3]}')
    
    if errors:
        print('❌ 内容校验失败:')
        for err in errors:
            print(f'  - {err}')
        return False
    
    log_path = os.path.join(instance_dir, '004-validation.log')
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f'[OK] 内容校验通过\n')
        f.write(f'[OK] H2数量: {h2_count}\n')
        f.write(f'[OK] FAQ模块: 存在\n')
        f.write(f'[OK] References: 通过\n')
    
    print(f'✅ 内容校验通过')
    print(f'   产出: {log_path}')
    return True

def main():
    parser = argparse.ArgumentParser(description='校验正文内容质量')
    parser.add_argument('--dir', required=True, help='实例目录')
    
    args = parser.parse_args()
    
    if validate_content(args.dir):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
