from hwp5.xmlmodel import Hwp5File

def get_hwp_text(filename):
    hwp = Hwp5File(filename)
    text = ""
    # BodyText 스트림에서 텍스트 노드 추출
    for section in hwp.bodytext.sections:
        for paragraph in section.paragraphs:
            text += paragraph.text + "\n"
    return text

print(get_hwp_text("[신용회복위원회]_GenOS_v1.9.1_정보자산 반출입 신청서 (1).hwp"))
