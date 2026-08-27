import os
import sys
import json
import re
import argparse
from pathlib import Path
from urllib.parse import urlparse

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from brand_site_url import normalize_brand_site_url, resolve_brand_site_url  # noqa: E402


def _brand_site_url(instance_dir, override=''):
    found = normalize_brand_site_url(override)
    if found:
        return found
    startup_path = os.path.join(instance_dir, '001 启动确认.md')
    if not os.path.exists(startup_path):
        return ''
    with open(startup_path, 'r', encoding='utf-8') as f:
        startup = f.read()
    return resolve_brand_site_url(startup, '')


def _validate_citations(body, errors):
    ref_marker = '## References'
    if ref_marker not in body:
        return 0, 0
    article, ref_section = body.split(ref_marker, 1)
    references = re.findall(
        r'^\s*(?:[-*]|\d+[.)])\s+\[([^\]]+)\]\((https?://[^)]+)\)',
        ref_section,
        re.MULTILINE,
    )
    citations = [int(value) for value in re.findall(r'(?<!\!)\[(\d+)\]', article)]
    ref_count = len(references)
    if not citations:
        errors.append('正文没有编号引用 [N]')
        return 0, ref_count
    out_of_range = sorted({number for number in citations if number < 1 or number > ref_count})
    if out_of_range:
        errors.append(
            f'正文引用编号越界: {out_of_range}，References 仅 {ref_count} 条'
        )
    unused = sorted(set(range(1, ref_count + 1)) - set(citations))
    if unused:
        errors.append(f'References 条目未被正文引用: {unused}')
    return len(citations), ref_count


def _brand_host(brand_site_url):
    return (urlparse(brand_site_url).hostname or '').lower().removeprefix('www.')


def _validate_internal_links(body, brand_site_url, errors):
    article = body.split('## References', 1)[0]
    links = re.findall(r'\[[^\]]+\]\((https?://[^)]+)\)', article)
    if not brand_site_url:
        errors.append('缺少品牌官网 URL，无法验证站内内部链接')
        return 0
    brand_host = _brand_host(brand_site_url)
    internal = [
        url
        for url in links
        if (urlparse(url).hostname or '').lower().removeprefix('www.') == brand_host
    ]
    if not internal:
        errors.append(f'正文缺少指向品牌域名 {brand_host} 的可点击内部链接')
    return len(internal)


def _validate_references_exclude_brand(body, brand_site_url, errors):
    if '## References' not in body or not brand_site_url:
        return 0
    brand_host = _brand_host(brand_site_url)
    if not brand_host:
        return 0
    ref_section = body[body.find('## References'):]
    brand_refs = [
        url
        for url in re.findall(r'https?://[^\s)]+', ref_section)
        if (urlparse(url).hostname or '').lower().removeprefix('www.') == brand_host
    ]
    for url in brand_refs:
        errors.append(f'References 包含品牌自有域名: {url}')
    return len(brand_refs)


def validate_content(instance_dir, brand_site_url=''):
    draft_path = os.path.join(instance_dir, '004 正文.md')
    bid_path = os.path.join(instance_dir, '000 BID.json')
    
    if not os.path.exists(draft_path):
        print('[FAIL] 004 正文.md 不存在')
        return False
    
    with open(draft_path, 'r', encoding='utf-8') as f:
        body = f.read()
    
    if not body.strip():
        print('[FAIL] 正文内容为空')
        return False
    
    errors = []
    
    h2_count = len(re.findall(r'^## ', body, re.MULTILINE))
    if h2_count < 4:
        errors.append(f'H2数量不足: {h2_count} < 4')
    
    if 'FAQ' not in body and len(re.findall(r'\?\n', body)) < 3:
        errors.append('缺少FAQ模块')
    
    ref_count = 0
    citation_count = 0
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
        citation_count, ref_count = _validate_citations(body, errors)

    site_url = _brand_site_url(instance_dir, brand_site_url)
    brand_ref_hits = _validate_references_exclude_brand(body, site_url, errors)
    internal_link_count = _validate_internal_links(body, site_url, errors)
    
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
        print('[FAIL] 内容校验失败:')
        for err in errors:
            print(f'  - {err}')
        return False
    
    log_path = os.path.join(instance_dir, '004-validation.log')
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f'[OK] 内容校验通过\n')
        f.write(f'[OK] H2数量: {h2_count}\n')
        f.write(f'[OK] FAQ模块: 存在\n')
        f.write(
            f'[OK] References: {ref_count} 条，正文引用 {citation_count} 处，编号双向对应\n'
        )
        f.write(f'[OK] References 无品牌自有域名: {brand_ref_hits == 0}\n')
        f.write(f'[OK] 品牌内部链接: {internal_link_count} 条\n')
    
    print('[OK] 内容校验通过')
    print(f'   产出: {log_path}')
    return True

def main():
    parser = argparse.ArgumentParser(description='校验正文内容质量')
    parser.add_argument('--dir', required=True, help='实例目录')
    parser.add_argument('--brand-site-url', default='', help='品牌官网 URL')
    
    args = parser.parse_args()
    
    if validate_content(args.dir, args.brand_site_url):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
