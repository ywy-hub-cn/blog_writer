import json
import os

def validate_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return True, None
    except json.JSONDecodeError as e:
        return False, f"JSON语法错误: {e}"
    except Exception as e:
        return False, f"读取错误: {e}"

def main():
    print("=" * 60)
    print("blog-writer 系统验证")
    print("=" * 60)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("\n1. 验证 registry.json")
    registry_path = os.path.join(base_dir, 'registry.json')
    ok, err = validate_json(registry_path)
    if ok:
        print("   ✅ registry.json 语法正确")
    else:
        print(f"   ❌ registry.json 错误: {err}")
    
    print("\n2. 验证节点文件 (nodes/)")
    nodes_dir = os.path.join(base_dir, 'nodes')
    all_ok = True
    for filename in sorted(os.listdir(nodes_dir)):
        if filename.endswith('.json'):
            filepath = os.path.join(nodes_dir, filename)
            ok, err = validate_json(filepath)
            if ok:
                print(f"   ✅ {filename}")
            else:
                print(f"   ❌ {filename}: {err}")
                all_ok = False
    
    print("\n3. 验证批量配置文件")
    batch_config_path = os.path.join(base_dir, 'batch-config.json')
    ok, err = validate_json(batch_config_path)
    if ok:
        print("   ✅ batch-config.json 语法正确")
    else:
        print(f"   ❌ batch-config.json 错误: {err}")
    
    print("\n4. 验证 registry.json 引用完整性")
    with open(registry_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)
    
    step_order = registry.get('step_order', [])
    routing = registry.get('routing', {})
    
    missing_files = []
    for step_file in step_order:
        filepath = os.path.join(nodes_dir, step_file)
        if not os.path.exists(filepath):
            missing_files.append(step_file)
    
    if missing_files:
        print(f"   ❌ step_order 中引用的文件不存在: {missing_files}")
    else:
        print("   ✅ step_order 引用的所有文件都存在")
    
    print("\n5. 验证路由配置")
    routing_errors = []
    for step_id, config in routing.items():
        on_pass = config.get('on_pass')
        on_fail = config.get('on_fail')
        
        if on_pass and on_pass not in routing and on_pass != '':
            routing_errors.append(f"{step_id}: on_pass={on_pass} 未定义")
        if on_fail and on_fail not in routing:
            routing_errors.append(f"{step_id}: on_fail={on_fail} 未定义")
    
    if routing_errors:
        for err in routing_errors:
            print(f"   ❌ {err}")
    else:
        print("   ✅ 路由配置完整")
    
    print("\n" + "=" * 60)
    if all_ok and not missing_files and not routing_errors:
        print("🎉 所有验证通过!")
    else:
        print("⚠️ 存在验证失败项，请检查上述错误")

if __name__ == '__main__':
    main()
