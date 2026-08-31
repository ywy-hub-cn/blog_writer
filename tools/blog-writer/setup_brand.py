import os
import sys
import shutil
import json
import re
import argparse
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from brand_site_url import pick_brand_site_url  # noqa: E402


def infer_role(filename):
    lower_name = filename.lower()
    if any(k in lower_name for k in ['禁用词', 'forbidden', '红线', '黑名单', '禁止']):
        return '禁用词'
    if any(k in lower_name for k in ['语气', '调性', 'tone', 'voice', 'style']):
        return '语气调性'
    if any(k in lower_name for k in ['受众', '画像', 'audience', 'persona']):
        return '受众画像'
    if any(k in lower_name for k in ['评审', 'review', '标准', 'criterion']):
        return '评审标准'
    if any(k in lower_name for k in ['调用', 'usage', '使用规则']):
        return '知识库规则'
    if any(k in lower_name for k in ['品牌知识', '知识库', 'knowledg']):
        return '品牌知识'
    if any(k in lower_name for k in ['visual', 'guideline', 'guidelines', '视觉规范', '视觉']):
        return '视觉规范'
    if any(k in lower_name for k in ['模板', 'template', '规范', 'seo', '颜色', 'asset']):
        return '其他'
    return '其他'

def extract_urls(content):
    url_pattern = re.compile(r'https?://[^\s<>"\']+')
    return list(set(url_pattern.findall(content)))


def parse_whitelist(raw: str):
    if not raw or not str(raw).strip():
        return []
    parts = re.split(r'[,，\n;；]+', str(raw))
    seen = set()
    out = []
    for p in parts:
        w = p.strip()
        if not w:
            continue
        key = w.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
        if len(out) >= 50:
            break
    return out

def main():
    parser = argparse.ArgumentParser(description='初始化品牌文件')
    parser.add_argument('--brand-path', required=True, help='品牌目录路径')
    parser.add_argument('--keywords', required=True, help='写作关键词')
    parser.add_argument('--out-dir', required=True, help='输出目录')
    parser.add_argument('--user-note', default='', help='用户附加要求')
    parser.add_argument('--brand-site-url', default='', help='品牌官网URL')
    parser.add_argument(
        '--forbidden-whitelist',
        default='',
        help='本次任务禁用词白名单（逗号/换行分隔，仅本任务生效）',
    )
    parser.add_argument(
        '--method-path',
        default='',
        help='方法母版路径（.method目录），如有则复制references到实例目录',
    )
    
    args = parser.parse_args()
    
    brand_path = args.brand_path
    out_dir = args.out_dir
    whitelist = parse_whitelist(args.forbidden_whitelist)
    
    if not os.path.exists(brand_path):
        print(f'ERROR: brand_path not found: {brand_path}')
        sys.exit(1)
    
    brand_files = [f for f in os.listdir(brand_path) if f.endswith('.md')]
    if not brand_files:
        print('ERROR: no .md files in brand_path')
        sys.exit(1)
    
    os.makedirs(os.path.join(out_dir, 'brand'), exist_ok=True)
    
    # 复制 .method/references 到实例目录（供S001等步骤读取参考文件）
    method_path = args.method_path
    if not method_path:
        # 自动探测：从脚本位置向上查找 .method 目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for candidate in [
            os.path.join(script_dir, '..', '..', '.method'),
            os.path.join(script_dir, '..', '.method'),
            os.path.join(os.getcwd(), '.method'),
        ]:
            if os.path.isdir(candidate):
                method_path = candidate
                break
    
    if method_path and os.path.isdir(method_path):
        refs_src = os.path.join(method_path, 'references')
        if os.path.isdir(refs_src):
            refs_dst = os.path.join(out_dir, '.method', 'references')
            os.makedirs(refs_dst, exist_ok=True)
            copied_refs = 0
            for ref_file in os.listdir(refs_src):
                if ref_file.endswith('.md') or ref_file.endswith('.json'):
                    src = os.path.join(refs_src, ref_file)
                    dst = os.path.join(refs_dst, ref_file)
                    shutil.copy2(src, dst)
                    copied_refs += 1
            if copied_refs > 0:
                print(f'   copied references: {copied_refs} files from {refs_src}')
    
    manifest = {
        'files': [],
        'has_brand_knowledge': False,
        'has_tone_guidelines': False,
        'has_forbidden_words': False,
        'has_audience_profile': False,
        'has_review_criteria': False,
        'has_visual_guidelines': False,
        'forbidden_whitelist': whitelist,
    }
    
    all_urls = []
    brand_sections = {}
    
    for filename in brand_files:
        src_path = os.path.join(brand_path, filename)
        dst_path = os.path.join(out_dir, 'brand', filename)
        shutil.copy2(src_path, dst_path)
        
        role = infer_role(filename)
        manifest['files'].append({
            'name': filename,
            'path': f'brand/{filename}',
            'inferred_role': role
        })
        
        if role == '品牌知识':
            manifest['has_brand_knowledge'] = True
        elif role == '语气调性':
            manifest['has_tone_guidelines'] = True
        elif role == '禁用词':
            manifest['has_forbidden_words'] = True
        elif role == '受众画像':
            manifest['has_audience_profile'] = True
        elif role == '评审标准':
            manifest['has_review_criteria'] = True
        elif role == '视觉规范':
            manifest['has_visual_guidelines'] = True
        
        with open(src_path, 'r', encoding='utf-8') as f:
            content = f.read()
            brand_sections.setdefault(role, [])
            brand_sections[role].append(content)
            all_urls.extend(extract_urls(content))
    
    wl_path = os.path.join(out_dir, 'forbidden_whitelist.json')
    with open(wl_path, 'w', encoding='utf-8') as f:
        json.dump({'words': whitelist, 'scope': 'this_task_only'}, f, ensure_ascii=False, indent=2)

    manifest_path = os.path.join(out_dir, 'brand', 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    brand_text_blob = "\n\n".join(
        "\n\n".join(parts) for parts in brand_sections.values()
    )
    site_url = pick_brand_site_url(
        args.brand_site_url,
        all_urls,
        brand_text=brand_text_blob,
    )
    site_display = site_url or "未提供"
    
    startup_content = f"""# 启动确认

## 基本信息
- **关键词**: {args.keywords}
- **用户备注**: {args.user_note}
- **品牌官网**: {site_display}
- **模式**: free
- **本次禁用词白名单**: {('、'.join(whitelist) if whitelist else '（无）')}

## 品牌官网
{site_display}

## 品牌文件清单
"""
    
    for file_info in manifest['files']:
        startup_content += f"- [{file_info['name']}]({file_info['path']}) → {file_info['inferred_role']}\n"
    
    startup_content += "\n"

    if whitelist:
        startup_content += "## 本次禁用词白名单\n"
        startup_content += (
            "> 仅本任务生效。下列词条在写作与 Gate 禁用词检测中豁免，"
            "不视为违规；未列入者仍按品牌禁用词清单拦截。\n\n"
        )
        for w in whitelist:
            startup_content += f"- {w}\n"
        startup_content += "\n"
    
    if manifest['has_brand_knowledge']:
        startup_content += "## 品牌知识原文\n"
        startup_content += "\n\n".join(brand_sections.get('品牌知识', [])) + "\n\n"
    
    if manifest['has_tone_guidelines']:
        startup_content += "## 语气调性原文\n"
        startup_content += "\n\n".join(brand_sections.get('语气调性', [])) + "\n\n"
    
    if manifest['has_forbidden_words']:
        startup_content += "## 禁用词原文\n"
        startup_content += "\n\n".join(brand_sections.get('禁用词', [])) + "\n\n"
    
    if manifest['has_audience_profile']:
        startup_content += "## 受众画像原文\n"
        startup_content += "\n\n".join(brand_sections.get('受众画像', [])) + "\n\n"
    
    if manifest['has_review_criteria']:
        startup_content += "## 评审标准原文\n"
        startup_content += "\n\n".join(brand_sections.get('评审标准', [])) + "\n\n"

    if manifest['has_visual_guidelines']:
        startup_content += "## 视觉规范原文\n"
        startup_content += "\n\n".join(brand_sections.get('视觉规范', [])) + "\n\n"
    
    if '其他' in brand_sections:
        startup_content += "## 其他参考原文\n"
        startup_content += "\n\n".join(brand_sections.get('其他', [])) + "\n\n"
    
    if all_urls:
        startup_content += "## 提取的URL\n"
        for url in all_urls[:20]:
            startup_content += f"- {url}\n"
    
    startup_path = os.path.join(out_dir, '001 启动确认.md')
    with open(startup_path, 'w', encoding='utf-8') as f:
        f.write(startup_content)
    
    print('OK: brand setup complete')
    print(f'   copied files: {len(brand_files)}')
    print(f'   brand_site_url: {site_display}')
    if whitelist:
        print(f'   whitelist ({len(whitelist)}): {", ".join(whitelist)}')
    print(f'   output: {startup_path}')
    print(f'   output: {manifest_path}')
    print(f'   output: {wl_path}')

if __name__ == '__main__':
    main()
