"""Cắt đoạn văn bản theo ngữ nghĩa dấu câu đa ngôn ngữ."""

from typing import List

# Các nhóm dấu câu theo thứ tự ưu tiên (đồng bộ với C# AudioProcessor)
PUNCTS_GROUP_1 = [". ", "? ", "! ", '." ', '?" ', '!" ', "。", "？", "！", "」"]
PUNCTS_GROUP_2 = [", ", "; ", " ", "、", "，", "；"]
PUNCTS_GROUP_3 = ["は", "が", "を", "に", "で", "て", "と", "の", "的", "了", "和"]

def split_text_by_sentences(text: str, max_length: int = 333) -> List[str]:
    """Chia văn bản thành các đoạn nhỏ không vượt quá max_length ký tự,
    ưu tiên ngắt ở dấu câu tự nhiên để đảm bảo giọng đọc liền mạch.
    """
    if not text:
        return []

    text = text.replace("\r\n", "\n")
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: List[str] = []

    for paragraph in paragraphs:
        p = paragraph
        while len(p) > max_length:
            split_pos = -1

            # Nhóm 1: Dấu chấm, hỏi, than, đóng ngoặc
            sub_window = p[:max_length + 2]
            for punct in PUNCTS_GROUP_1:
                # Tìm vị trí xuất hiện cuối cùng trong phạm vi cho phép
                pos = sub_window.rfind(punct)
                if pos != -1 and pos <= max_length:
                    candidate = pos + len(punct) - (1 if punct.endswith(" ") else 0)
                    if candidate > split_pos:
                        split_pos = candidate

            # Nhóm 2: Dấu phẩy, chấm phẩy, khoảng trắng
            if split_pos == -1:
                for punct in PUNCTS_GROUP_2:
                    pos = sub_window.rfind(punct)
                    if pos != -1 and pos <= max_length:
                        candidate = pos + len(punct) - (1 if punct.endswith(" ") else 0)
                        if candidate > split_pos:
                            split_pos = candidate

            # Nhóm 3: Trợ từ Á Đông (Nhật, Trung)
            if split_pos == -1:
                for punct in PUNCTS_GROUP_3:
                    pos = sub_window.rfind(punct)
                    if pos != -1 and pos <= max_length:
                        candidate = pos + len(punct)
                        if candidate > split_pos:
                            split_pos = candidate

            # Nếu không tìm thấy dấu câu nào phù hợp, ngắt cứng tại max_length
            if split_pos <= 0:
                split_pos = max_length

            chunk = p[:split_pos].strip()
            if chunk:
                chunks.append(chunk)
            p = p[split_pos:].strip()

        if p:
            chunks.append(p)

    return chunks
