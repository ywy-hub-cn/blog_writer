import os
import sys
import json
import argparse
import re


def validate_brand_config(brand_path):
    errors = []
    warnings = []
    
    if not os.path.exists(brand_path):
        errors.append(f"品牌目录不存在: {brand_path}")
        return errors, warnings
    
    md_files = [f for f in os.listdir(brand_path) if f.endswith('.md')]
    
    if len(md_files) == 0:
        errors.append("品牌目录中没有 .md 文件")
    elif len(md_files) < 2:
        warnings.append("品牌文件较少，建议至少包含知识库和语气指南")
    
    has_knowledge = False
    has_tone = False
    has_forbidden = False
    
    for filename in md_files:
        filepath = os.path.join(brand_path, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().lower()
        
        if any(k in filename.lower() for k in ['知识', 'knowledg', '产品', '公司']):
            has_knowledge = True
        if any(k in filename.lower() for k in ['语气', '调性', 'tone', 'style', 'voice']):
            has_tone = True
        if any(k in filename.lower() for k in ['禁用', 'forbidden', '红线', '禁止']):
            has_forbidden = True
    
    if not has_knowledge:
        warnings.append("建议添加品牌知识库文件")
    if not has_tone:
        warnings.append("建议添加语气调性指南文件")
    if not has_forbidden:
        warnings.append("建议添加禁用词清单")
    
    return errors, warnings


def validate_keywords(keywords):
    errors = []
    warnings = []
    
    if not keywords or not keywords.strip():
        errors.append("关键词不能为空")
    elif len(keywords) < 2:
        warnings.append("关键词过短，建议更具体")
    elif len(keywords) > 100:
        warnings.append("关键词过长，建议精简")
    
    forbidden_patterns = [
        r'(免费|永久|保证|承诺|绝对)',
        r'(第一|最好|最佳|唯一|顶级)',
        r'(绝对化|极限词)'
    ]
    
    for pattern in forbidden_patterns:
        if re.search(pattern, keywords):
            warnings.append(f"关键词含敏感词汇，可能违反广告法: {keywords}")
            break
    
    return errors, warnings


def validate_mode(mode):
    errors = []
    warnings = []
    
    valid_modes = ['auto', 'supervised', 'manual']
    if mode not in valid_modes:
        errors.append(f"无效的模式: {mode}，有效值为: {', '.join(valid_modes)}")
    
    return errors, warnings


def validate_config_file(config_path):
    errors = []
    warnings = []
    
    if not os.path.exists(config_path):
        errors.append(f"配置文件不存在: {config_path}")
        return errors, warnings
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"JSON格式错误: {e}")
        return errors, warnings
    
    if 'brand_path' in config:
        err, warn = validate_brand_config(config['brand_path'])
        errors.extend(err)
        warnings.extend(warn)
    elif 'default_brand_path' in config:
        err, warn = validate_brand_config(config['default_brand_path'])
        errors.extend(err)
        warnings.extend(warn)
    
    if 'keywords' in config:
        err, warn = validate_keywords(config['keywords'])
        errors.extend(err)
        warnings.extend(warn)
    
    if 'mode' in config:
        err, warn = validate_mode(config['mode'])
        errors.extend(err)
        warnings.extend(warn)
    
    if 'tasks' in config:
        tasks = config['tasks']
        if not isinstance(tasks, list):
            errors.append("tasks 必须是数组")
        elif len(tasks) == 0:
            warnings.append("tasks 为空，没有任务可执行")
        else:
            for i, task in enumerate(tasks):
                if not isinstance(task, dict):
                    errors.append(f"tasks[{i}] 必须是对象")
                    continue
                
                if 'keywords' in task:
                    err, warn = validate_keywords(task['keywords'])
                    for e in err:
                        errors.append(f"tasks[{i}]. {e}")
                    for w in warn:
                        warnings.append(f"tasks[{i}]. {w}")
                
                if 'mode' in task:
                    err, warn = validate_mode(task['mode'])
                    for e in err:
                        errors.append(f"tasks[{i}]. {e}")
                    for w in warn:
                        warnings.append(f"tasks[{i}]. {w}")
    
    return errors, warnings


def validate_registry(config_dir):
    errors = []
    warnings = []
    
    registry_path = os.path.join(config_dir, 'registry.json')
    if not os.path.exists(registry_path):
        errors.append(f"registry.json 不存在: {registry_path}")
        return errors, warnings
    
    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"registry.json 格式错误: {e}")
        return errors, warnings
    
    step_order = registry.get('step_order', [])
    if not step_order:
        errors.append("step_order 为空")
    
    nodes_dir = os.path.join(config_dir, 'nodes')
    for node_file in step_order:
        node_path = os.path.join(nodes_dir, node_file)
        if not os.path.exists(node_path):
            errors.append(f"节点文件不存在: {node_path}")
        else:
            try:
                with open(node_path, 'r', encoding='utf-8') as f:
                    node = json.load(f)
                    if 'id' not in node:
                        errors.append(f"{node_file} 缺少 id 字段")
                    if 'name' not in node:
                        errors.append(f"{node_file} 缺少 name 字段")
            except json.JSONDecodeError:
                errors.append(f"{node_file} JSON格式错误")
    
    routing = registry.get('routing', {})
    for step_id, route in routing.items():
        for key in ['on_pass', 'on_fail']:
            target = route.get(key)
            if target and target != '':
                found = False
                for node_file in step_order:
                    node_path = os.path.join(nodes_dir, node_file)
                    if os.path.exists(node_path):
                        with open(node_path, 'r', encoding='utf-8') as f:
                            node = json.load(f)
                            if node.get('id') == target:
                                found = True
                                break
                if not found:
                    warnings.append(f"路由目标不存在: {step_id}.{key} → {target}")
    
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description='校验 Blog-Writer 配置')
    parser.add_argument('--config', help='配置文件路径（单次或批量）')
    parser.add_argument('--brand-path', help='品牌目录路径')
    parser.add_argument('--keywords', help='关键词')
    parser.add_argument('--mode', help='运行模式')
    parser.add_argument('--config-dir', default='blog-writer', help='方法目录路径')
    parser.add_argument('--registry-only', action='store_true', help='只校验 registry')
    
    args = parser.parse_args()
    
    all_errors = []
    all_warnings = []
    
    if args.config:
        errors, warnings = validate_config_file(args.config)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    if args.brand_path:
        errors, warnings = validate_brand_config(args.brand_path)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    if args.keywords:
        errors, warnings = validate_keywords(args.keywords)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    if args.mode:
        errors, warnings = validate_mode(args.mode)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    if args.config_dir:
        errors, warnings = validate_registry(args.config_dir)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    if not args.config and not args.brand_path and not args.keywords and not args.mode and not args.registry_only:
        errors, warnings = validate_registry(args.config_dir)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    print("\n" + "="*60)
    print("Blog-Writer 配置校验报告")
    print("="*60)
    
    if all_errors:
        print(f"\n❌ 错误 ({len(all_errors)} 个):")
        for err in all_errors:
            print(f"  - {err}")
    
    if all_warnings:
        print(f"\n⚠️ 警告 ({len(all_warnings)} 个):")
        for warn in all_warnings:
            print(f"  - {warn}")
    
    if not all_errors and not all_warnings:
        print("\n✅ 所有配置校验通过！")
    
    print("\n" + "="*60)
    
    if all_errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
