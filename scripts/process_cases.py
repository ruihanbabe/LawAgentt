import pandas as pd
import json
import re
import os

# ===== 1. 正则提取函数定义 (容错设计) =====

def extract_case_id(text):
    """提取案号：如（2017）粤0306民初3474号"""
    if not isinstance(text, str): return None
    match = re.search(r'（\d{4}）[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁]?\w*民\w*号', text)
    return match.group(0) if match else None

def extract_case_type(text):
    """提取案由：过滤掉常见的公司后缀词，只保留XXX纠纷"""
    if not isinstance(text, str): return None
    # 匹配“纠纷”，但排除前面的公司标识（如“有限公司侵权责任纠纷” -> “侵权责任纠纷”）
    match = re.search(r'(?:公司|企业|厂|局|院|所|中心|集团|支行|分行)?([\u4e00-\u9fa5]+纠纷)', text)
    if match:
        case_type = match.group(1)
        # 兜底：如果提取出来的案由太长（超过10个字），大概率还是混入了公司名，截取后三个字+纠纷
        if len(case_type) > 10:
            return case_type[-6:] if case_type.endswith('纠纷') else case_type
        return case_type
    return None

def infer_entity_type(text, role_keyword):
    """推断角色类型：支持多被告混合情况，返回列表如 ['自然人', '法人']"""
    if not isinstance(text, str): return None
    lines = text.split('\n')
    types = set() # 用 set 去重，比如多个自然人被告只存一个'自然人'
    
    is_role_line = False
    for line in lines:
        # 找到“原告：”或“被告：”所在的行
        if role_keyword in line and ('：' in line or ':' in line):
            is_role_line = True
        
        # 只要还在连续的当事人信息行（处理多被告换行的情况）
        if is_role_line:
            if re.search(r'公司|企业|厂|局|院|所|中心|集团', line):
                types.add("法人")
            else:
                types.add("自然人")
                
            # 如果这行没有标点结尾，且下一行不是空行，说明多被告信息还在继续
            # 如果遇到了空行或新的结构词（如“诉请”、“委托”），停止判定
            if line.strip() == '' or '委托' in line or '法定' in line:
                is_role_line = False

    if not types:
        return None
    
    # 转为列表，为了后续 Qdrant 的 Payload 数组过滤 (如 defendant_type contains "法人")
    return list(types)

def extract_claim_amount(text):
    """提取诉讼标的额：提取诉请段落的第一个金额"""
    if not isinstance(text, str): return None
    
    # 尝试定位诉请段（通常在文书前半部分）
    suit_part = text[:1000] if len(text) > 1000 else text
    
    # 匹配金额：支持逗号分隔和小数，如 1,234,567.89 元 或 163755.57元
    amounts = re.findall(r'(\d[\d,]*\.?\d*)\s*元', suit_part)
    
    if amounts:
        # 取诉请段找到的第一个金额（通常是总标的额）
        first_amount_str = amounts[0].replace(',', '')
        try:
            return float(first_amount_str)
        except ValueError:
            return None
    return None

# ===== 2. 主处理流程 =====

def process_csv_to_json(csv_path, output_path, max_rows=20):
    """读取 CSV 前 N 行，提取结构化数据，输出 JSON"""
    # 读取 CSV
    try:
        df = pd.read_csv(csv_path, nrows=max_rows)
    except Exception as e:
        print(f"读取 CSV 失败: {e}")
        return
    
    results = []
    
    for idx, row in df.iterrows():
        # 兼容不同的 CSV 列名
        input_text = row.get('input', row.get('全文', ''))
        output_text = row.get('output', row.get('摘要', ''))
        row_id = row.get('id', f"case_{idx}")
        
        # 执行正则提取
        case_id = extract_case_id(input_text)
        case_type = extract_case_type(input_text)
        plaintiff_type = infer_entity_type(input_text, "原告")
        defendant_type = infer_entity_type(input_text, "被告")
        claim_amount = extract_claim_amount(input_text)
        
        # 组装 JSON 对象
        payload = {
            "id": f"case_{row_id}",
            "case_id": case_id,
            "case_type": case_type,
            "plaintiff_type": plaintiff_type,
            "defendant_type": defendant_type,
            "claim_amount": claim_amount,
            "content": input_text,
            "summary": output_text
        }
        
        results.append(payload)
        
        # 打印提取日志，方便调试
        print(f"Row {idx}: case_id={case_id}, type={case_type}, P={plaintiff_type}, D={defendant_type}, Amt={claim_amount}")

        # 保存为 JSON

    dir_name = os.path.dirname(output_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True) # 自动创建缺失的目录
        
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    
    print(f"\n✅ 处理完成！输出 {len(results)} 条数据至 {output_path}")

# ===== 3. 运行 =====
if __name__ == "__main__":
    # 请将 your_data.csv 替换为你实际的 CSV 文件名
    process_csv_to_json(
        csv_path="/root/LawAgent/data/raw_discus/DISC-Law-SFT-Pair.csv", 
        output_path="/root/LawAgent/data/chinese-cases.json",
        max_rows=20
    )
