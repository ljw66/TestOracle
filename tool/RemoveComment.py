import json
from pathlib import Path


def remove_c_comments(code):
    """
    删除C代码中的注释
    保留字符串和字符常量中的内容
    """
    
    result = []
    
    i = 0
    n = len(code)
    
    in_string = False
    in_char = False
    in_single_comment = False
    in_multi_comment = False
    
    while i < n:
        
        c = code[i]
        
        # 单行注释
        if in_single_comment:
            if c == '\n':
                in_single_comment = False
                result.append(c)
            i += 1
            continue
        
        # 多行注释
        if in_multi_comment:
            if c == '*' and i + 1 < n and code[i + 1] == '/':
                in_multi_comment = False
                i += 2
            else:
                i += 1
            continue
        
        # 字符串
        if in_string:
            result.append(c)
            
            if c == '\\' and i + 1 < n:
                result.append(code[i + 1])
                i += 2
                continue
            
            if c == '"':
                in_string = False
            
            i += 1
            continue
        
        # 字符常量
        if in_char:
            result.append(c)
            
            if c == '\\' and i + 1 < n:
                result.append(code[i + 1])
                i += 2
                continue
            
            if c == '\'':
                in_char = False
            
            i += 1
            continue
        
        # 进入字符串
        if c == '"':
            in_string = True
            result.append(c)
            i += 1
            continue
        
        # 进入字符常量
        if c == '\'':
            in_char = True
            result.append(c)
            i += 1
            continue
        
        # 检测注释
        
        if c == '/' and i + 1 < n:
            
            # //
            if code[i + 1] == '/':
                in_single_comment = True
                i += 2
                continue
            
            # /*
            if code[i + 1] == '*':
                in_multi_comment = True
                i += 2
                continue
        
        result.append(c)
        i += 1
    
    return ''.join(result)


def process_json(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if "function_code" in data:
        data["function_pure_code"] = remove_c_comments(
            data["function_code"]
        )
    
    with open(input_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


def process_directory(input_dir):
    input_dir = Path(input_dir)
    json_files = list(input_dir.rglob("*.json"))
    
    print(f"Found {len(json_files)} files")
    
    for json_file in json_files:
        try:
            process_json(json_file)
            print(f"✓ {json_file}")
        
        except Exception as e:
            print(f"✗ {json_file}")
            print(e)


if __name__ == "__main__":
    process_directory(input_dir="D:\\Paper\\TestOracle\\expr\\2\\CTU02-all\\CTU02\\test")
