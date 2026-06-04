import json
import os
import re
from datetime import datetime

def clean_article_content(raw_text):
    """
    清洗法条内容，移除开头的法条引用部分。
    例如：将 "《中华人民共和国反家庭暴力法》第八条规定，县级以上人民政府..." 
    清洗为 "县级以上人民政府..."
    """
    import re
    
    # 匹配模式：法典名称 + "第" + 条款序号 + "条规定，"
    pattern = r'^《([^》]+)》第([一二三四五六七八九十百千零\d]+)条规定，(.+)$'
    
    match = re.match(pattern, raw_text)
    if match:
        # 返回纯净内容
        return match.group(3).strip()
    else:
        # 如果不符合模式，返回原始文本（可能是其他格式）
        return raw_text.strip()

def extract_referenced_laws(text):
    """
    从文本中提取引用的法条。
    例如：从 "依照《民法典》第577条、《反家庭暴力法》第8条的规定..." 
    提取为 ["民法典第577条", "反家庭暴力法第8条"]
    """
    import re
    
    # 匹配模式：法典名称 + "第" + 条款序号 + "条"
    pattern = r'《([^》]+)》第?([一二三四五六七八九十百千零\d]+)条'
    matches = re.findall(pattern, text)
    
    # 将匹配结果格式化为 "法典名第X条" 的列表
    referenced_laws = [f"{law}第{article}条" for law, article in matches]
    
    return referenced_laws

def extract_amount(text):
    """
    从文本中提取金额信息。
    例如：从 "借款金额不得超过5万元" 提取为 50000.0
    """
    import re
    
    # 匹配阿拉伯数字金额，如 "5万元", "50,000元", "50000.00元"
    arabic_pattern = r'(\d{1,3}(?:[,，]\d{3})*(?:\.\d+)?)\s*元'
    arabic_matches = re.findall(arabic_pattern, text)
    
    # 匹配中文大写金额（简化处理，仅匹配"元"结尾）
    chinese_pattern = r'([壹贰叁肆伍陆柒捌玖拾佰仟万亿零整]+)元'
    chinese_matches = re.findall(chinese_pattern, text)
    
    amounts = []
    for amount in arabic_matches:
        # 移除逗号，转换为浮点数
        amounts.append(float(amount.replace(',', '').replace('，', '')))
    
    # 如果找到金额，返回第一个；否则返回None
    return amounts[0] if amounts else None
def chinese_to_arabic(chinese_num):
    """将中文数字转换为阿拉伯数字"""
    chinese_digits = {
        '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
        '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
        '百': '100', '千': '1000', '万': '10000', '零': '0'
    }
    
    # 处理单个数字（如 "一"）
    if len(chinese_num) == 1:
        return chinese_digits.get(chinese_num, '0')
    
    # 处理 "十一" 到 "十九"
    if chinese_num.startswith('十'):
        if len(chinese_num) == 2:
            return '10'  # "十"
        else:
            return str(10 + int(chinese_digits.get(chinese_num[1:], '0')))
    
    # 处理其他情况（如 "二十一"）
    return chinese_digits.get(chinese_num, '0')


def extract_law_info(text):
    """
    从原始文本中提取法典名称和条号。
    """
    import re
    
    pattern = r'^《([^》]+)》第([一二三四五六七八九十百千零\d]+)条规定，'
    match = re.match(pattern, text)
    
    if match:
        law_name = match.group(1)
        article_number = match.group(2)
        
        # 将中文数字转换为阿拉伯数字
        article_id = chinese_to_arabic(article_number)
        
        return law_name, article_number, article_id
    else:
        # 如果不符合模式，返回默认值
        return "未知法典", "未知条号", "0"

def process_law_files(input_dir, output_file):
    """
    处理法条文件，生成JSON格式数据
    """
    laws = []
    print (input_dir)
    
    # 遍历所有txt文件
    for filename in os.listdir(input_dir):
        if filename.endswith('.txt'):
            filepath = os.path.join(input_dir, filename)
            
            # 读取文件内容
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 按行处理
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # 清洗内容
                clean_content = clean_article_content(line)
                
                # 提取法典名称和条号
                law_name, article_number, article_id = extract_law_info(line)
                
                # 提取引用法条
                referenced_laws = extract_referenced_laws(line)
                
                # 提取金额
                amount = extract_amount(line)
                
                # 生成唯一ID
                unique_id = f"law_{law_name}_{article_id}"
                
                # 创建JSON对象
                law_data = {
                    "id": unique_id,
                    "law_name": law_name,
                    "article_number": article_number,
                    "article_id": article_id,
                    "content": clean_content,
                    "referenced_laws": referenced_laws,
                    "amount": amount
                }
                
                laws.append(law_data)
    
    # 保存为JSON文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(laws, f, ensure_ascii=False, indent=2)
    
    print(f"处理完成，共生成 {len(laws)} 条法条数据")

# 使用示例
if __name__ == "__main__":
    # 假设你的法条数据在 data/Chinese-Laws 目录下
    input_directory = "/root/agent/data/Chinese-Laws"
    # 输出文件将保存在 data/chinese-laws.json
    output_file = "data/chinese-laws.json"
    
    process_law_files(input_directory, output_file)
