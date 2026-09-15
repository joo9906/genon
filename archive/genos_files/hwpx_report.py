import json
from lxml import etree
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path
from openai import OpenAI
from copy import deepcopy
from dotenv import load_dotenv

load_dotenv()

template_file = 'template_new_format.hwpx'
extract_dir = Path('./report/new_content')

print(Path)

if not extract_dir.exists():
    extract_dir.mkdir(parents=True, exist_ok=True)


json_data = {
    "department1_name": "신용회복위원회 지원부서",
    "department2_name": "신용회복위원회 지원부서",
    "manager1": "김XX 부장(02-750-1092)",
    "manager2": "이XX 심사역(02-750-1093)",
    "number": 1,
    "distribution_date": "2026.05.15.(금)",
    "title":"",
    "sub_title1": "",
    "sub_title2": "",
    "contents": []
}


# 1. HWPX 압축 해제
with ZipFile(template_file, 'r') as z:
    z.extractall(extract_dir)

print("Unzip completed.")

# 2. HWPX 내 XML 파일 읽기

section_xml_path = extract_dir / "Contents" / "section0.xml"

with open(section_xml_path, 'r', encoding="UTF-8") as f:
    section_xml = f.read()


# 3. 텍스트 탐색 및 치환(LLM-based)
with open('./template_prompt.md', 'r', encoding="UTF-8") as f:
    system_prompt = f.read()

json_data = json.dumps(json_data, ensure_ascii=False)
subject = "신용회복위원회가 제논과 생성형 AI 구축 사업 추진한다."

user_prompt = f"""
        [JSON DATA]
        {json_data}

        [REPORT_SUBJECT]
        {subject}
    """

client = OpenAI()
response = client.chat.completions.create(
    model = "gpt-5.4-mini",
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ],
    temperature=1
)


result = response.choices[0].message.content

with open('./result/llm_result.json', 'w') as f:
    f.write(result)

# 4. XML(section0.xml) 덮어쓰기
section_xml_path = extract_dir / "Contents" / "section0.xml"

# with open ('llm_output.json', 'r', encoding='utf-8') as f:
#     result = f.read()

# modified_xml = llm_output["modified_xml"]

result = json.loads(result)
contents = result["contents"]

tree = etree.parse(section_xml_path)
root = tree.getroot()

ns = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"
}


replacements = {
    '{{title}}': result['title'],
    '{{sub_title1}}': result['sub_title1'],
    '{{sub_title2}}': result['sub_title2'],
    '{{department1_name}}': result['department1_name'],
    '{{department2_name}}': result['department2_name'],
    '{{manager1}}': result['manager1'],
    '{{manager2}}': result['manager2'],
    '{{number}}': str(result['number']),
    '{{distribution_date}}': result['distribution_date'],
}

for t in root.iter('{http://www.hancom.co.kr/hwpml/2011/paragraph}t'):
    if t.text:
        new_text = t.text
        for k, v in replacements.items():
            if k in new_text:
                new_text = new_text.replace(k, v if v is not None else '')
        t.text = new_text

# □ 문단: <hp:t> 안에 '□ '로 시작하는 텍스트가 있는 <hp:p>
square_template = root.xpath(
    './/hp:p[hp:run/hp:t[starts-with(text(), "□")]]',
    namespaces=ns
)[0]

# ◦ 문단: <hp:t> 안에 '◦'가 포함된 텍스트가 있는 <hp:p>
circle_template = root.xpath(
    './/hp:p[hp:run/hp:t[contains(text(), "◦")]]',
    namespaces=ns
)[0]

# spacer: □ 문단과 ◦ 문단 사이의 빈 줄 (paraPrIDRef="15")
# spacer_template = root.xpath(
#     './/hp:p[@paraPrIDRef="15"]',
#     namespaces=ns
# )[0]
spacer_template = circle_template.getnext()


##################################
print(f"square_template paraPr: {square_template.get('paraPrIDRef')}")
print(f"circle_template paraPr: {circle_template.get('paraPrIDRef')}")
print(f"spacer_template paraPr: {spacer_template.get('paraPrIDRef')}")

# spacer가 정말 빈 줄인지 확인 (텍스트가 없어야 정상)
spacer_text = ''.join(
    (t.text or '') for t in spacer_template.findall('.//hp:t', ns)
)
print(f"spacer_template 안 텍스트: {repr(spacer_text)}  (빈 문자열이어야 정상)")
###################################



parent = square_template.getparent()
insert_index = parent.index(square_template)

for item in contents:
    print(f"item: {item}")
    # □ 문단
    square_p = deepcopy(square_template)
    t = square_p.xpath('.//hp:t[contains(text(), "{{main}}")]', namespaces=ns)[0]
    t.text = t.text.replace('{{main}}', item["main"])
    parent.insert(insert_index, square_p)

    insert_index += 1

    # ◦ 문단
    detail = item.get("detail")
    if detail:
        circle_p = deepcopy(circle_template)
        t = circle_p.xpath('.//hp:t[contains(text(), "{{detail}}")]', namespaces=ns)[0]
        t.text = t.text.replace('{{detail}}', item["detail"])
        parent.insert(insert_index, circle_p)

        insert_index += 1

    spacer_p = deepcopy(spacer_template)
    parent.insert(insert_index, spacer_p)

    insert_index += 1

square_template.getparent().remove(square_template)
circle_template.getparent().remove(circle_template)
if spacer_template.getparent():
    spacer_template.getparent().remove(spacer_template)

tree.write(
    section_xml_path,
    encoding="utf-8",
    xml_declaration=False
)

'''
xml_string = etree.tostring(
    tree,
    encoding='unicode',
    pretty_print=True
)

with open(section_xml_path, 'w', encoding='utf-8') as f:
    f.write(xml_string)
'''

# 5. HWPX 압축 및 출력
output_path = "hwpx_output_report11.hwpx"

with ZipFile(output_path, "w", ZIP_DEFLATED) as z:
    for file_path in extract_dir.rglob('*'):
        if file_path.is_file():

            arcname = file_path.relative_to(extract_dir)

            z.write(file_path, arcname)

print("HWPX report generation completed.")