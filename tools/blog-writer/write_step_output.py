import os
import sys
import json
import argparse

def write_step_output(output_type, file_path, data):
    if output_type == 'gate':
        write_gate_result(file_path, data)
    elif output_type == 'review':
        write_review_result(file_path, data)
    else:
        write_generic(file_path, data)

def write_gate_result(file_path, data):
    content = f"""# Gate 校验结果

## 校验结果
- **状态**: {'✅ 通过' if data.get('passed') else '❌ 未通过'}

## 校验清单
"""
    
    checklist = data.get('checklist', {})
    items = [
        ('hook', '首屏与定位'),
        ('structure', '结构与可读性'),
        ('quality', '内容质量'),
        ('seo', 'SEO一致性'),
        ('clean', '格式洁净度')
    ]
    
    for key, label in items:
        status = '✅' if checklist.get(key) else '❌'
        content += f"- {status} {label}: {'通过' if checklist.get(key) else '未通过'}\n"
    
    content += "\n"
    
    issues = data.get('issues', [])
    if issues:
        content += "## 问题列表\n"
        for i, issue in enumerate(issues, 1):
            content += f"{i}. {issue}\n"
        content += "\n"
    
    note = data.get('note', '')
    if note:
        content += f"## 备注\n{note}\n"
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'OK: Gate结果已写入 {file_path}')

def write_review_result(file_path, data):
    content = f"""# 自审结果

## 审核结果
- **状态**: {'✅ 通过' if data.get('passed') else '❌ 未通过'}
- **总分**: {data.get('total_score', 0)}/100

## 评分明细
"""
    
    scores = data.get('scores', {})
    score_items = [
        ('intent_match', '意图匹配', 10),
        ('keyword_coverage', '关键词覆盖', 10),
        ('content_value', '内容价值', 10),
        ('readability', '可读性', 10),
        ('seo_basics', 'SEO基础', 10),
        ('eeat', 'E-E-A-T', 10),
        ('ux_conversion', '转化率', 10),
        ('originality', '原创性', 10),
        ('aigc_trace', 'AIGC痕迹', 10),
        ('mechanical', '机械感', 10)
    ]
    
    for key, label, max_score in score_items:
        score = scores.get(key, 0)
        content += f"- {label}: {score}/{max_score}\n"
    
    content += "\n"
    
    issues = data.get('issues', [])
    if issues:
        content += "## 问题列表\n"
        for i, issue in enumerate(issues, 1):
            content += f"{i}. {issue}\n"
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'OK: 自审结果已写入 {file_path}')

def write_generic(file_path, data):
    content = json.dumps(data, indent=2, ensure_ascii=False)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'OK: 结果已写入 {file_path}')

def main():
    parser = argparse.ArgumentParser(description='写入步骤输出')
    parser.add_argument('--type', required=True, choices=['gate', 'review', 'generic'], help='输出类型')
    parser.add_argument('--file', required=True, help='输出文件路径')
    
    args = parser.parse_args()
    
    json_text = sys.stdin.read().strip()
    if not json_text:
        print('❌ 未提供JSON数据')
        sys.exit(1)
    
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f'❌ JSON解析错误: {e}')
        sys.exit(1)
    
    write_step_output(args.type, args.file, data)
    sys.exit(0)

if __name__ == '__main__':
    main()
