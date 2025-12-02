import os
import io
import json
import re
import random
import base64
import string
from PIL import Image
from datetime import datetime
from flask import send_file, send_from_directory, Response, stream_with_context
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, current_app

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import google.generativeai as genai
import PyPDF2
import pytz

from google.cloud import texttospeech
from utils.ocr import extract_text_from_image
from utils.gemini_api import analyze_text_with_gemini
from datetime import datetime, timezone

datetime.now(timezone.utc)

app = Flask(__name__)
app.secret_key = "phuonganh2403"

vn_timezone = pytz.timezone('Asia/Ho_Chi_Minh')
timestamp = datetime.now(vn_timezone).strftime("%Y-%m-%d %H:%M:%S")

os.environ["GOOGLE_API_KEY"] = "AIzaSyAbd_vx7BwYXlL0S-J6vXnPrmebtK5bNkk"
########### 
### AIzaSyDx4KnyXaBKZIVHiFuiDjBUwkX8tPY8XuQ
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

model = genai.GenerativeModel("models/gemini-2.0-flash")
app.config['UPLOAD_FOLDER'] = 'uploads'

def load_context(topic):
    file_map = {
        "tam_li": "data_tam_li.txt",
        "stress": "stress.txt",
        "nghe_nghiep": "nghe_nghiep.txt"
    }
    file_path = file_map.get(topic, "data_tam_li.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Không tìm thấy dữ liệu phù hợp."

def build_prompt(topic, context_data, user_input, is_first_message=False):
    context_summary = context_data[:1500] if context_data else ""
    
    if topic == "tam_li":
        intro = "Chào bạn, tôi là trợ lý AI Tâm An chuyên về lĩnh vực tâm lí.\n\n" if is_first_message else ""
        return (
            f"tôi là trợ lý AI Tâm An chuyên về lĩnh vực tâm lí.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Ưu tiên dùng dữ liệu trên nếu liên quan\n"
            f"- Nếu không có trong dữ liệu, dùng kiến thức chung của bạn để trả lời\n"
            f"- KHÔNG BAO GIỜ nói 'xin lỗi, không có dữ liệu' hay 'nằm ngoài phạm vi'\n"
            f"- Trả lời tự nhiên, thân thiện như một cuộc hội thoại bình thường\n"
            f"- Câu đầu tiên: giới thiệu. Từ câu 2 trở đi: không cần giới thiệu lại\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
    elif topic == "stress":
        intro = "Chào bạn, tôi là trợ lý AI Tâm An, chuyên hỗ trợ tâm lý và stress.\n\n" if is_first_message else ""
        return (
            f"Bạn là trợ lý AI giúp học sinh vượt qua căng thẳng.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Trả lời với giọng điệu trấn an, đồng cảm\n"
            f"- Dùng dữ liệu nếu có, không thì dùng kiến thức chung\n"
            f"- KHÔNG nói 'xin lỗi, không biết'\n"
            f"- Trò chuyện tự nhiên, không rập khuôn\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
    elif topic == "nghe_nghiep":
        intro = "Chào bạn, tôi là trợ lý AI của cô Tâm An, chuyên tư vấn định hướng nghề nghiệp.\n\n" if is_first_message else ""
        return (
            f"Bạn là trợ lý AI tư vấn nghề nghiệp cho học sinh.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Khích lệ, giúp học sinh khám phá bản thân\n"
            f"- Dùng dữ liệu nếu có, không thì đưa ra lời khuyên từ kiến thức chung\n"
            f"- KHÔNG từ chối trả lời\n"
            f"- Trò chuyện tự nhiên\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
    else:
        intro = "Chào bạn, tôi là trợ lý AI của cô Tâm An.\n\n" if is_first_message else ""
        return (
            f"Bạn là trợ lý AI thân thiện.\n"
            f"Dữ liệu tham khảo:\n{context_summary}\n\n"
            f"QUY TẮC:\n"
            f"- Trả lời tự nhiên, thân thiện\n"
            f"- Dùng cả dữ liệu và kiến thức chung\n"
            f"- KHÔNG từ chối hay xin lỗi khi không có dữ liệu\n\n"
            f"{intro}Câu hỏi: {user_input}\n"
            f"Trả lời:"
        )
##################
@app.route("/tro_chuyen_tam_li_cung_tro_ly_ai_pham_hang", methods=["GET", "POST"])
def tam_li_chat():
    topic = request.args.get("topic", "tam_li")
    context_data = load_context(topic)
    response_text = ""
    
    if request.method == "POST":
        user_input = request.form.get("user_input")
        if user_input:
            is_first = session.get(f'first_message_{topic}', True)
            
            prompt = build_prompt(topic, context_data, user_input, is_first_message=is_first)
            response = model.generate_content(prompt)
            response_text = response.text
            
            # ✅ LOẠI BỎ MARKDOWN
            response_text = response_text.replace('###', '')
            response_text = response_text.replace('***', '')
            response_text = response_text.replace('**', '')
            response_text = response_text.replace('* ', '')
            response_text = response_text.replace('- ', '')
            response_text = response_text.replace('• ', '')
            
            # ✅ XỬ LÝ XUỐNG DÒNG CHO CÁC SỐ THỨ TỰ
            import re
            # Thêm 2 dòng trống trước các số thứ tự (1., 2., 3., 4., etc.)
            response_text = re.sub(r'(\d+\.)', r'\n\n\1', response_text)
            
            # ✅ LOẠI BỎ DÒNG TRỐNG THỪA
            # Loại bỏ dòng trống ở đầu văn bản
            response_text = response_text.lstrip()
            # Giảm dòng trống thừa (3+ dòng → 2 dòng)
            response_text = re.sub(r'\n{3,}', '\n\n', response_text)
            
            # ✅ XỬ LÝ XUỐNG DÒNG SAU DẤU CHẤM HỎI
            # Thêm dòng mới sau câu hỏi nếu câu tiếp theo bắt đầu bằng số hoặc chữ in hoa
            response_text = re.sub(r'\?\s+(\d+\.|\w)', r'?\n\n\1', response_text)
            
            session[f'first_message_{topic}'] = False
    
    return render_template("tam_li.html", response=response_text, topic=topic)
    ##########################3
def read_pdf(file_path):
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        print(f"Lỗi đọc PDF {file_path}: {e}")
    return text

custom_data = ""

if os.path.exists("data.txt"):
    with open("data.txt", "r", encoding="utf-8") as f:
        custom_data += f.read() + "\n"
        
pdf_folder = "data"
if os.path.exists(pdf_folder):
    for file_name in os.listdir(pdf_folder):
        if file_name.lower().endswith(".pdf"):
            file_path = os.path.join(pdf_folder, file_name)
            custom_data += read_pdf(file_path) + "\n"

docs_list = [
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D21",
        "link": "https://drive.google.com/file/d/1qIS83JH_9OpTk_tR9bwhl61F_EETPaFk/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D22",
        "link": "https://drive.google.com/file/d/1dxNrWXjxLlO97ZAAb-E-s56n6peCYrqp/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D23",
        "link": "https://drive.google.com/file/d/16jaAmn-87QN7kiYzB7dIcF0fjRGpPLJg/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D24",
        "link": "https://drive.google.com/file/d/1p8GQ5aHna5H8q0ujq26tK7uqjT5v3P-1/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D25",
        "link": "https://drive.google.com/file/d/1IUtEbTVS4-mRmyBEV6gbDGjHxJHAtgSf/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D26",
        "link": "https://drive.google.com/file/d/1CXVEz6NPRusUaVJE3HRTOBm6neYbcmge/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D27",
        "link": "https://drive.google.com/file/d/1NlCO6a7kTCortwWU0BC2Yme3sTH4xBOV/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT 28",
        "link": "https://drive.google.com/file/d/1M7FLkTU4P35ljfghkjvuDEHV1k5ZrTv3/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D29",
        "link": "https://drive.google.com/file/d/1Ob-hF8P1_itOvZoKWk0JUNzpLxQTGHdZ/view?usp=sharing"
    },
    {
        "title": "Bộ đề tham tham khảo lịch sử THPT D30",
        "link": "https://drive.google.com/file/d/16_xfgmEqr_HSF2rD0jLZOj00CTDiSfDQ/view?usp=sharing"
    },
    {
        "title": "Tài liệu ôn thi",
        "link": "https://drive.google.com/file/d/1N23yjH5L4f5ySms8Q3dlXllB9YmG5Lt2/view?usp=drive_link"
    },
    {
        "title": "Kiến thức trọng tâm",
        "link": "https://drive.google.com/file/d/1NPZIZkZ0q9PEY1JdV9zjSvtJD_0ykEo2/view?usp=drive_link"
    }
]

@app.route('/')
def menu():
    return render_template('menu.html')

@app.route('/stress_test', methods=['GET', 'POST'])
def stress_test():
    if request.method == 'POST':
        answers = {int(k): int(v) for k, v in request.form.items()}
        group_D = [3, 5, 10, 13, 16, 17, 21]  
        group_A = [2, 4, 7, 9, 15, 19, 20]    
        group_S = [1, 6, 8, 11, 12, 14, 18]

        score_D = sum(answers[q] for q in group_D) * 2
        score_A = sum(answers[q] for q in group_A) * 2
        score_S = sum(answers[q] for q in group_S) * 2

        def classify_D(score):
            if score <= 9: return "Bình thường"
            elif score <= 13: return "Nhẹ"
            elif score <= 20: return "Vừa"
            elif score <= 27: return "Nặng"
            else: return "Rất nặng"

        def classify_A(score):
            if score <= 7: return "Bình thường"
            elif score <= 9: return "Nhẹ"
            elif score <= 14: return "Vừa"
            elif score <= 19: return "Nặng"
            else: return "Rất nặng"

        def classify_S(score):
            if score <= 14: return "Bình thường"
            elif score <= 18: return "Nhẹ"
            elif score <= 25: return "Vừa"
            elif score <= 33: return "Nặng"
            else: return "Rất nặng"

        return render_template(
            'stress_result.html',
            score_D=score_D, score_A=score_A, score_S=score_S,
            level_D=classify_D(score_D),
            level_A=classify_A(score_A),
            level_S=classify_S(score_S)
        )

    questions = [
        "Tôi thấy khó mà thoải mái được",
        "Tôi bị khô miệng",
        "Tôi dường như chẳng có chút cảm xúc tích cực nào",
        "Tôi bị rối loạn nhịp thở (thở gấp, khó thở dù chẳng làm việc gì nặng)",
        "Tôi thấy khó bắt tay vào công việc",
        "Tôi có xu hướng phản ứng thái quá với mọi tình huống",
        "Tôi bị ra mồ hôi (chẳng hạn như mồ hôi tay...)",
        "Tôi thấy mình đang suy nghĩ quá nhiều",
        "Tôi lo lắng về những tình huống có thể làm tôi hoảng sợ hoặc biến tôi thành trò cười",
        "Tôi thấy mình chẳng có gì để mong đợi cả",
        "Tôi thấy bản thân dễ bị kích động",
        "Tôi thấy khó thư giãn được",
        "Tôi cảm thấy chán nản, thất vọng",
        "Tôi không chấp nhận được việc có cái gì đó xen vào cản trở việc tôi đang làm",
        "Tôi thấy mình gần như hoảng loạn",
        "Tôi không thấy hứng thú với bất kỳ việc gì nữa",
        "Tôi cảm thấy mình chẳng đáng làm người",
        "Tôi thấy mình khá dễ phát ý, tự ái",
        "Tôi nghe thấy rõ tiếng nhịp tim dù chẳng làm việc gì",
        "Tôi hay sợ vô cớ",
        "Tôi thấy cuộc sống vô nghĩa"
    ]
    return render_template('stress_test.html', questions=questions)

questions_holland = [
    {"text": "Tôi thích sửa chữa máy móc, thiết bị.", "type": "R"},
    {"text": "Tôi thích nghiên cứu, tìm hiểu hiện tượng tự nhiên.", "type": "I"},
    {"text": "Tôi thích vẽ, viết hoặc sáng tạo nghệ thuật.", "type": "A"},
    {"text": "Tôi thích làm việc nhóm và giúp đỡ người khác.", "type": "S"},
    {"text": "Tôi thích thuyết phục và lãnh đạo người khác.", "type": "E"},
    {"text": "Tôi thích làm việc với số liệu, giấy tờ và sắp xếp hồ sơ.", "type": "C"},
    {"text": "Tôi thích làm việc ngoài trời.", "type": "R"},
    {"text": "Tôi tò mò về cách mọi thứ hoạt động.", "type": "I"},
    {"text": "Tôi yêu thích âm nhạc, hội họa hoặc sân khấu.", "type": "A"},
    {"text": "Tôi dễ dàng kết bạn và trò chuyện với người lạ.", "type": "S"},
    {"text": "Tôi thích điều hành dự án hoặc quản lý một nhóm.", "type": "E"},
    {"text": "Tôi thích nhập dữ liệu hoặc làm việc hành chính.", "type": "C"},
    {"text": "Tôi thích vận hành máy móc hoặc công cụ.", "type": "R"},
    {"text": "Tôi thích giải quyết các bài toán hoặc vấn đề phức tạp.", "type": "I"},
    {"text": "Tôi thích thiết kế hoặc tạo ra sản phẩm sáng tạo.", "type": "A"},
    {"text": "Tôi thích giúp đỡ người khác giải quyết vấn đề cá nhân.", "type": "S"},
    {"text": "Tôi thích bán hàng hoặc tiếp thị sản phẩm.", "type": "E"},
    {"text": "Tôi thích theo dõi và lưu trữ hồ sơ cẩn thận.", "type": "C"},
    {"text": "Tôi thích sửa chữa xe cộ hoặc đồ điện tử.", "type": "R"},
    {"text": "Tôi thích tìm hiểu về khoa học hoặc công nghệ mới.", "type": "I"},
    {"text": "Tôi thích viết truyện, thơ hoặc kịch bản.", "type": "A"},
    {"text": "Tôi thích giảng dạy hoặc huấn luyện người khác.", "type": "S"},
    {"text": "Tôi thích lập kế hoạch kinh doanh.", "type": "E"},
    {"text": "Tôi thích quản lý dữ liệu và hồ sơ.", "type": "C"},
    {"text": "Tôi thích làm công việc xây dựng hoặc sửa chữa nhà cửa.", "type": "R"},
    {"text": "Tôi thích thực hiện thí nghiệm.", "type": "I"},
    {"text": "Tôi thích sáng tác nhạc hoặc viết lời bài hát.", "type": "A"},
    {"text": "Tôi thích làm công tác xã hội hoặc tình nguyện.", "type": "S"},
    {"text": "Tôi thích lãnh đạo chiến dịch hoặc dự án.", "type": "E"},
    {"text": "Tôi thích lập bảng tính hoặc tài liệu thống kê.", "type": "C"},
    {"text": "Tôi thích đi bộ đường dài hoặc các hoạt động ngoài trời.", "type": "R"},
    {"text": "Tôi thích phân tích dữ liệu hoặc nghiên cứu thị trường.", "type": "I"},
    {"text": "Tôi thích chụp ảnh hoặc quay phim.", "type": "A"},
    {"text": "Tôi thích chăm sóc sức khỏe cho người khác.", "type": "S"},
    {"text": "Tôi thích phát triển chiến lược tiếp thị.", "type": "E"},
    {"text": "Tôi thích thực hiện công việc kế toán hoặc tài chính.", "type": "C"},
    {"text": "Tôi thích lắp ráp hoặc tháo rời thiết bị.", "type": "R"},
    {"text": "Tôi thích đọc sách khoa học hoặc tài liệu chuyên môn.", "type": "I"},
    {"text": "Tôi thích tham gia vào các hoạt động nghệ thuật cộng đồng.", "type": "A"},
    {"text": "Tôi thích hỗ trợ tâm lý cho người gặp khó khăn.", "type": "S"},
    {"text": "Tôi thích đàm phán hợp đồng hoặc thỏa thuận.", "type": "E"},
    {"text": "Tôi thích kiểm tra lỗi trong dữ liệu.", "type": "C"},
    {"text": "Tôi thích chế tạo hoặc lắp ráp thủ công.", "type": "R"},
    {"text": "Tôi thích đặt câu hỏi và tìm hiểu nguyên nhân sự việc.", "type": "I"},
    {"text": "Tôi thích làm đồ thủ công mỹ nghệ.", "type": "A"},
    {"text": "Tôi thích tổ chức các sự kiện cộng đồng.", "type": "S"},
    {"text": "Tôi thích khởi nghiệp kinh doanh.", "type": "E"},
    {"text": "Tôi thích làm việc theo quy trình rõ ràng.", "type": "C"},
    {"text": "Tôi thích sử dụng công cụ hoặc máy móc nặng.", "type": "R"},
    {"text": "Tôi thích nghiên cứu công nghệ mới.", "type": "I"},
    {"text": "Tôi thích biểu diễn trước khán giả.", "type": "A"},
    {"text": "Tôi thích đào tạo và phát triển kỹ năng cho người khác.", "type": "S"},
    {"text": "Tôi thích thuyết phục người khác mua sản phẩm.", "type": "E"},
    {"text": "Tôi thích sắp xếp và phân loại tài liệu.", "type": "C"},
    {"text": "Tôi thích sửa chữa các thiết bị điện gia dụng.", "type": "R"},
    {"text": "Tôi thích khám phá và nghiên cứu những điều mới lạ.", "type": "I"},
    {"text": "Tôi thích viết kịch bản hoặc đạo diễn phim.", "type": "A"},
    {"text": "Tôi thích hỗ trợ người khuyết tật.", "type": "S"},
    {"text": "Tôi thích quản lý nhân sự.", "type": "E"},
    {"text": "Tôi thích theo dõi sổ sách và ngân sách.", "type": "C"}
]

holland_types = {
    "R": {
        "name": "Realistic (Kỹ thuật, thực tế)",
        "desc": "Thích làm việc tay chân, máy móc, kỹ thuật, ngoài trời.",
        "jobs": [
            "Kỹ sư cơ khí",
            "Thợ điện",
            "Kỹ thuật viên ô tô",
            "Công nhân xây dựng",
            "Kỹ sư nông nghiệp"
        ]
    },
    "I": {
        "name": "Investigative (Nghiên cứu)",
        "desc": "Thích phân tích, tìm tòi, khám phá, làm việc khoa học.",
        "jobs": [
            "Nhà khoa học",
            "Bác sĩ",
            "Kỹ sư phần mềm",
            "Nhà nghiên cứu y sinh",
            "Chuyên gia dữ liệu"
        ]
    },
    "A": {
        "name": "Artistic (Nghệ thuật)",
        "desc": "Thích sáng tạo, tự do, nghệ thuật, biểu diễn.",
        "jobs": [
            "Họa sĩ",
            "Nhà thiết kế đồ họa",
            "Nhạc sĩ",
            "Đạo diễn",
            "Nhiếp ảnh gia"
        ]
    },
    "S": {
        "name": "Social (Xã hội)",
        "desc": "Thích giúp đỡ, giao tiếp, dạy học, hỗ trợ cộng đồng.",
        "jobs": [
            "Giáo viên",
            "Nhân viên xã hội",
            "Nhà tâm lý học",
            "Điều dưỡng",
            "Hướng dẫn viên du lịch"
        ]
    },
    "E": {
        "name": "Enterprising (Quản lý, kinh doanh)",
        "desc": "Thích lãnh đạo, kinh doanh, thuyết phục, mạo hiểm.",
        "jobs": [
            "Doanh nhân",
            "Nhà quản lý dự án",
            "Chuyên viên marketing",
            "Luật sư",
            "Nhân viên bán hàng"
        ]
    },
    "C": {
        "name": "Conventional (Hành chính)",
        "desc": "Thích công việc văn phòng, chi tiết, tuân thủ quy trình.",
        "jobs": [
            "Nhân viên kế toán",
            "Thư ký",
            "Nhân viên nhập liệu",
            "Nhân viên hành chính",
            "Chuyên viên tài chính"
        ]
    }
}

@app.route("/relax/<mode>")
def relax_page(mode):
    valid_modes = ["menu", "music", "yoga", "meditation", "breathing"]
    if mode not in valid_modes:
        return "Trang không tồn tại", 404
    return render_template(f"relax_{mode}.html")

@app.route("/holland", methods=["GET", "POST"])
def holland_test():
    if request.method == "POST":
        scores = {key: 0 for key in holland_types.keys()}
        for idx in range(1, len(questions_holland) + 1):
            ans = request.form.get(str(idx))
            if ans and ans.isdigit():
                scores[questions_holland[idx - 1]["type"]] += int(ans) - 1
        sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        top3_details = [
            {
                "code": t[0],
                "name": holland_types[t[0]]["name"],
                "desc": holland_types[t[0]]["desc"],
                "jobs": holland_types[t[0]]["jobs"],
                "score": t[1]
            }
            for t in sorted_types[:3]
        ]

        return render_template(
            "holland_result.html",
            top3_details=top3_details
        )

    return render_template("holland.html", questions=questions_holland)

USERS_FILE = 'users.json'
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        users = load_users()

        if username in users and users[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('emotion_journal'))
        else:
            return render_template('login.html', message="Sai tên đăng nhập hoặc mật khẩu")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        users = load_users()

        if username in users:
            return render_template('register.html', message="Tên đăng nhập đã tồn tại")
        if len(users) >= 20:
            return render_template('register.html', message="Đã đủ 20 tài khoản test")

        users[username] = {"password": password, "logs": []}
        save_users(users)
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/emotion_journal', methods=['GET', 'POST'])
def emotion_journal():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    users = load_users()
    history = users.get(username, {}).get('logs', [])

    music_videos = {
        "Giảm căng thẳng": "https://www.youtube.com/embed/e8fFEmMW5EI&t",
        "Piano": "https://www.youtube.com/embed/tVQ_uDRs_7U",
        "Bình yên": "https://www.youtube.com/embed/MLQZOGJeBLA"
    }

    tz_vn = pytz.timezone('Asia/Ho_Chi_Minh')

    if request.method == 'POST':
        emotion = request.form.get('emotion')
        note = request.form.get('note', '').strip()
        activities = request.form.getlist('activities')
        
        timestamp = datetime.now(tz_vn).strftime("%d/%m/%Y %H:%M:%S")

        new_entry = {
            'datetime': timestamp,
            'emotion': emotion,
            'note': note,
            'activities': activities
        }
        history.append(new_entry)
        users[username]['logs'] = history
        save_users(users)

        message = "Ghi lại cảm xúc thành công!"
        return render_template('emotion_journal.html',
                               message=message,
                               history=history,
                               music_videos=music_videos)

    return render_template('emotion_journal.html',
                           history=history,
                           music_videos=music_videos)

@app.route('/export_pdf')
def export_pdf():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    users = load_users()
    history = users.get(username, {}).get('logs', [])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()

    font_path = os.path.join('fonts', 'Roboto-VariableFont_wdth,wght.ttf')
    pdfmetrics.registerFont(TTFont('Roboto', font_path))

    for style_name in styles.byName:
        styles[style_name].fontName = 'Roboto'

    elements = []
    elements.append(Paragraph(f"📔 Nhật ký cảm xúc của {username}", styles['Title']))
    elements.append(Spacer(1, 20))

    if not history:
        elements.append(Paragraph("Không có dữ liệu cảm xúc.", styles['Normal']))
    else:
        for i, entry in enumerate(history, start=1):
            elements.append(Paragraph(f"<b>#{i}</b> - {entry['datetime']}", styles['Heading3']))
            elements.append(Paragraph(f"Cảm xúc: {entry['emotion']}", styles['Normal']))
            elements.append(Paragraph(f"Hoạt động: {', '.join(entry['activities'])}", styles['Normal']))
            elements.append(Paragraph(f"Ghi chú: {entry['note']}", styles['Normal']))
            elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"nhat_ky_cam_xuc_{username}.pdf",
                     mimetype='application/pdf')

@app.route("/")
def main_menu():
    return render_template("menu.html")

@app.route("/docs")
def docs():
    return render_template("docs.html", docs=docs_list)

@app.route("/chatbot")
def chatbot_page():
    return render_template("index.html")

@app.route("/chat_stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    
    if not user_message:
        return jsonify({"error": "Không có tin nhắn"}), 400
    
    def generate():
        try:
            if 'chat_history' not in session:
                session['chat_history'] = []
            
            chat_history = session['chat_history']
            
            is_first = len(chat_history) == 0
            intro = "Chào bạn, tôi là trợ lý AI của cô Phạm Hằng về lịch sử.\n\n" if is_first else ""
            
            context = ""
            if len(chat_history) > 0:
                recent_history = chat_history[-6:]
                context = "Lịch sử hội thoại:\n"
                for i in range(0, len(recent_history), 2):
                    if i+1 < len(recent_history):
                        context += f"Người dùng: {recent_history[i]}\nTrợ lý: {recent_history[i+1]}\n"
                context += "\n"
            
            prompt = f"""
Bạn là trợ lý AI thông minh của cô Phạm Hằng chuyên về lịch sử.
Dữ liệu tham khảo (ưu tiên nếu liên quan):
{custom_data[:1500]}

{context}

QUY TẮC QUAN TRỌNG:
- Ưu tiên dùng dữ liệu trên nếu câu hỏi liên quan
- Nếu không có trong dữ liệu, TỰ TIN trả lời bằng kiến thức tổng quát của bạn
- TUYỆT ĐỐI KHÔNG nói "xin lỗi, không có dữ liệu" hay "nằm ngoài phạm vi kiến thức"
- Trả lời tự nhiên, thân thiện như một cuộc trò chuyện thực tế
- Nếu hỏi tiếp về câu trước, hãy dựa vào lịch sử hội thoại để trả lời liền mạch
- Nếu họ dùng tiếng Việt thì trả lời bằng tiếng Việt
- Chỉ giới thiệu ở câu đầu tiên, từ câu 2 trở đi trò chuyện bình thường
- KHÔNG dùng markdown format (###, ***, **, -, •)
- Trả lời dạng văn xuôi tự nhiên, KHÔNG dùng bullet points
- Nếu cần liệt kê, viết thành câu văn: "Có 3 điều quan trọng: thứ nhất..., thứ hai..., thứ ba..."

{intro}Câu hỏi hiện tại: {user_message}
Trả lời:
"""
            
            response = model.generate_content(
                prompt,
                stream=True,
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "max_output_tokens": 1024,
                }
            )
            
            chat_history.append(user_message)
            full_response = ""
            
            for chunk in response:
                if chunk.text:
                    clean_text = chunk.text
                    clean_text = clean_text.replace('###', '')
                    clean_text = clean_text.replace('***', '')
                    clean_text = clean_text.replace('**', '')
                    clean_text = clean_text.replace('* ', '')
                    clean_text = clean_text.replace('- ', '')
                    clean_text = clean_text.replace('• ', '')
                    
                    full_response += clean_text
                    data = json.dumps({"text": clean_text}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            
            chat_history.append(full_response)
            
            if len(chat_history) > 20:
                chat_history = chat_history[-20:]
            
            session['chat_history'] = chat_history
            session.modified = True
            
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            error_msg = f"Lỗi: {str(e)}"
            yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    
    if 'chat_history' not in session:
        session['chat_history'] = []
    
    chat_history = session['chat_history']
    is_first = len(chat_history) == 0
    intro = "Chào bạn, tôi là trợ lý AI của cô Phạm Hằng về lịch sử.\n\n" if is_first else ""
    
    context = ""
    if len(chat_history) > 0:
        recent_history = chat_history[-6:]
        context = "Lịch sử hội thoại:\n"
        for i in range(0, len(recent_history), 2):
            if i+1 < len(recent_history):
                context += f"Người dùng: {recent_history[i]}\nTrợ lý: {recent_history[i+1]}\n"
        context += "\n"
    
    prompt = f"""
Bạn là trợ lý AI thông minh của cô Phạm Hằng chuyên về lịch sử.
Dữ liệu tham khảo (ưu tiên nếu liên quan):
{custom_data[:1500]}

{context}

QUY TẮC QUAN TRỌNG:
- Ưu tiên sử dụng dữ liệu trên nếu câu hỏi liên quan
- Nếu không có trong dữ liệu, TỰ TIN trả lời bằng kiến thức của bạn
- KHÔNG BAO GIỜ nói "xin lỗi, không có dữ liệu" hoặc "nằm ngoài phạm vi"
- Trả lời tự nhiên, thân thiện như cuộc hội thoại thực tế
- Nếu hỏi tiếp về câu trước, dựa vào lịch sử để trả lời liền mạch
- Nếu họ nói tiếng Việt thì trả lời bằng tiếng Việt
- Câu đầu tiên có thể giới thiệu ngắn gọn, từ câu 2 trở đi không cần
- KHÔNG dùng markdown format (###, ***, **, -, •)
- Trả lời dạng văn xuôi tự nhiên

{intro}Câu hỏi hiện tại: {user_message}
Trả lời:
    """
    
    response = model.generate_content(prompt)
    reply_text = response.text
    
    reply_text = reply_text.replace('###', '')
    reply_text = reply_text.replace('***', '')
    reply_text = reply_text.replace('**', '')
    reply_text = reply_text.replace('* ', '')
    reply_text = reply_text.replace('- ', '')
    reply_text = reply_text.replace('• ', '')
    
    chat_history.append(user_message)
    chat_history.append(reply_text)
    
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]
    
    session['chat_history'] = chat_history
    session.modified = True
    
    return jsonify({"reply": reply_text})

@app.route("/clear_chat", methods=["POST"])
def clear_chat():
    session['chat_history'] = []
    session.modified = True
    return jsonify({"status": "ok"})

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "replies")
os.makedirs(AUDIO_DIR, exist_ok=True)

def load_user_data():
    try:
        with open("data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
###############################################
def random_filename(prefix="reply", ext="mp3", n=8):
    s = "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return f"{prefix}_{s}.{ext}"

def contains_english(text):
    return bool(re.search(r'[A-Za-z]', text))

@app.route("/replies/<path:filename>")
def serve_reply_audio(filename):
    return send_from_directory(AUDIO_DIR, filename, as_attachment=False)

@app.route("/chat_tam_an", methods=["POST"])
def chat_tam_an():
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Không có message"}), 400

    user_data = load_user_data()
    prompt = f"""Dưới đây là dữ liệu cá nhân của người dùng:
{json.dumps(user_data, ensure_ascii=False, indent=2)}

QUY TẮC BẮT BUỘC:
- Chỉ trả lời bằng tiếng Việt, không dùng từ/cụm từ tiếng Anh.
- Nếu mô hình dự định dùng từ tiếng Anh, hãy thay bằng từ tiếng Việt tương đương.
- Giọng thân thiện, tự nhiên như một người bạn.
- Câu trả lời ngắn gọn, dưới 3 câu.
- KHÔNG sử dụng markdown (**, ##, ###) trong câu trả lời.

Người dùng hỏi: {user_message}
"""
    try:
        resp = model.generate_content(prompt)
        text_reply = resp.text.strip()
        
        # Format lại response: loại bỏ markdown
        text_reply = text_reply.replace('**', '')
        text_reply = text_reply.replace('##', '')
        text_reply = text_reply.replace('###', '')
        
    except Exception as e:
        print("Lỗi khi gọi Gemini:", e)
        text_reply = "Xin lỗi, hiện tại tôi không thể trả lời ngay. Bạn thử lại sau nhé."

    if contains_english(text_reply):
        try:
            follow_prompt = prompt + "\n\nBạn đã sử dụng từ tiếng Anh, hãy trả lời lại hoàn toàn bằng tiếng Việt."
            resp2 = model.generate_content(follow_prompt)
            text_reply = resp2.text.strip()
            
            # Format lại lần nữa sau khi retry
            text_reply = text_reply.replace('**', '')
            text_reply = text_reply.replace('##', '')
            text_reply = text_reply.replace('###', '')
            
        except Exception as e:
            print("Lỗi follow-up Gemini:", e)

    audio_filename = None
    try:
        tts_client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text_reply)
        voice = texttospeech.VoiceSelectionParams(
            language_code="vi-VN",
            name="vi-VN-Wavenet-A",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0
        )

        tts_response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        audio_filename = random_filename()
        audio_path = os.path.join(AUDIO_DIR, audio_filename)
        with open(audio_path, "wb") as f:
            f.write(tts_response.audio_content)
    except Exception as e:
        print("Lỗi Google TTS:", e)
        audio_filename = None

    result = {"reply": text_reply}
    if audio_filename:
        result["audio_url"] = f"/replies/{audio_filename}"
    else:
        result["audio_url"] = None

    return jsonify(result)
####################################################
def load_exam(de_id):
    with open('exam_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get(de_id)
###########################################################3
@app.route('/index_td')
def index_td():
    return render_template('index_tn.html')
#########################################################
@app.route('/exam/<de_id>')
def exam(de_id):
    questions = load_exam(de_id)
    if not questions:
        return "Không tìm thấy đề thi."

    video_url = questions.get("video")
    return render_template('exam.html', questions=questions, de_id=de_id, video_url=video_url)

@app.route('/submit/<de_id>', methods=['GET', 'POST'])
def submit(de_id):
    if request.method != 'POST':
        return redirect(url_for('exam', de_id=de_id))

    questions = load_exam(de_id)
    if not questions:
        return "Không tìm thấy đề thi."

    correct_count = 0
    total_questions = 0
    feedback = []
    results = []

    for i, q in enumerate(questions.get("multiple_choice", [])):
        user_answer = request.form.get(f"mc_{i}")
        correct = q["answer"]
        total_questions += 1
        if user_answer and user_answer.strip().lower() == correct.strip().lower():
            correct_count += 1
            results.append({"status": "Đúng", "note": ""})
        else:
            msg = f"Câu {i+1} sai. Đáp án đúng là: {correct}"
            results.append({"status": "Sai", "note": msg})
            feedback.append(msg)

    for i, tf in enumerate(questions.get("true_false", [])):
        for j, correct_tf in enumerate(tf["answers"]):
            user_tf_raw = request.form.get(f"tf_{i}_{j}", "").lower()
            user_tf = user_tf_raw == "true"
            total_questions += 1
            if user_tf == correct_tf:
                correct_count += 1
                results.append({"status": "Đúng", "note": ""})
            else:
                msg = f"Câu {i+1+len(questions['multiple_choice'])}, ý {j+1} sai."
                results.append({"status": "Sai", "note": msg})
                feedback.append(msg)

    score = correct_count
    summary = f"Học sinh làm đúng {correct_count} / {total_questions} câu."
    try:
        prompt = (
            f"{summary}\n\n"
            "Dưới đây là danh sách các lỗi học sinh mắc phải:\n"
            + "\n".join(feedback) + "\n\n"
            "Bạn là giáo viên lịch sử. Hãy:\n"
            "1. Nhận xét tổng thể bài làm\n"
            "2. Phân tích từng lỗi sai (nêu lý do sai, giải thích kiến thức liên quan)\n"
            "3. Đề xuất ít nhất 3 dạng bài tập cụ thể để học sinh luyện tập đúng phần bị sai"
        )
        response = model.generate_content([prompt])
        ai_feedback = response.text
        
        # Format lại response: thay thế markdown bằng HTML
        ai_feedback = ai_feedback.replace('**', '')
        ai_feedback = ai_feedback.replace('##', '')
        ai_feedback = ai_feedback.replace('###', '')
        ai_feedback = ai_feedback.replace('\n', '<br>')
        
    except Exception as e:
        ai_feedback = f"⚠ Lỗi khi gọi AI: {str(e)}"
    
    return render_template(
        'result.html',
        score=score,
        feedback=feedback,
        ai_feedback=ai_feedback,
        total_questions=total_questions,
        results=results
    )

# TIÊU CHÍ CHẤM ĐIỂM từ file data_2.txt
RUBRIC_CRITERIA = """
HỆ THỐNG TIÊU CHÍ CHẤM ĐIỂM (10 điểm):

Câu 1 (1,5 điểm):
- Năng lực: Trình bày được nội dung chính về đặc điểm của các lực lượng cách mạng và vai trò của nghị quyết (0,5 điểm)  
- Kể tên các nhân vật lịch sử, sự kiện và phản ánh năng lực phân tích (0,25 điểm)
- Mức độ đầy đủ về các vấn đề liên quan đến nội dung câu hỏi (0,25 điểm)
- Trong thời đại ngày nay, phân tích vai trò của các lực lượng và ý nghĩa trong bối cảnh hiện tại (0,25 điểm)
- Công xót người dân về việc phát triển và xây dựng lực lượng cách mạng (0,25 điểm)

Câu 2 (1,5 điểm):
- Em hãy nêu khái niệm và vai trò của lực lượng dân tộc trong sự nghiệp cách mạng (0,5 điểm)
- Năng lực phân tích bối cảnh lịch sử và vai trò của ngoại lực (0,5 điểm)
- Viết mạch lạc, có luận cứ về vai trò của các yếu tố trong phong trào cách mạng (0,5 điểm)
"""


def generate_grading_prompt():
    """Tạo prompt chấm điểm dựa trên rubric"""
    
    prompt = f"""Bạn là giáo viên Lịch sử chấm bài. Hãy phân tích bài làm trong ảnh theo TIÊU CHÍ SAU:

{RUBRIC_CRITERIA}

YÊU CẦU CHẤM BÀI:
1. Đọc kỹ bài làm của học sinh trong ảnh
2. Chấm điểm CHI TIẾT cho TỪNG TIÊU CHÍ theo đúng thang điểm
3. Phân tích theo format BẮT BUỘC:

📊 TỔNG ĐIỂM: [X/3]

📝 ĐIỂM CHI TIẾT:

**CÂU 1 ([X]/1.5 điểm):**
- Tiêu chí 1 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 2 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 3 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 4 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 5 (0.25đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]

**CÂU 2 ([X]/1.5 điểm):**
- Tiêu chí 1 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 2 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]
- Tiêu chí 3 (0.5đ): [ĐẠT/CHƯA ĐẠT] - [Nhận xét cụ thể]



❌ LỖI SAI CẦN SỬA (nếu có):
- "Trích nguyên văn lỗi trong bài" → Sửa: [giải thích đúng]
- "Trích nguyên văn lỗi khác" → Sửa: [giải thích đúng]

💡 GỢI Ý CẢI THIỆN:
[1-2 câu ngắn gọn để học sinh cải thiện bài làm]

LƯU Ý QUAN TRỌNG:
- Phải TRÍCH NGUYÊN VĂN câu/đoạn sai trong bài làm (đặt trong dấu ngoặc kép)
- Chỉ ra lỗi CỤ THỂ: sai sự kiện, sai năm tháng, sai khái niệm, thiếu logic, thiếu độ sâu...
- Chấm điểm CÔNG BẰNG theo đúng thang điểm từng tiêu chí
- Tối đa 200 từ, ngắn gọn súc tích"""

    return prompt


@app.route('/upload_image', methods=['GET', 'POST'])
def upload_image():
    ai_feedback = None

    if request.method == 'POST':
        image = request.files.get('image')
        if not image or image.filename == '':
            return render_template('upload_image.html', feedback="⚠ Không có ảnh được chọn.")

        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
        image.save(image_path)

        try:
            img = Image.open(image_path)
            
            # SỬ DỤNG PROMPT MỚI với rubric chi tiết
            prompt = generate_grading_prompt()

            # Gọi model AI (thay 'model' bằng model của bạn)
            response = model.generate_content([img, prompt])
            ai_feedback = response.text
            
            # Format lại response để hiển thị đẹp
            ai_feedback = format_feedback_html(ai_feedback)
            
        except Exception as e:
            ai_feedback = f"⚠ Lỗi khi xử lý ảnh: {str(e)}"

    return render_template('upload_image.html', feedback=ai_feedback)


def format_feedback_html(text):
    """Format feedback thành HTML đẹp"""
    
    # Thay thế markdown bold
    text = text.replace('**', '<strong>').replace('**', '</strong>')
    
    # Thêm màu sắc cho các phần
    text = text.replace('📊 TỔNG ĐIỂM:', '<div class="total-score">📊 TỔNG ĐIỂM:')
    text = text.replace('📝 ĐIỂM CHI TIẾT:', '</div><div class="details">📝 ĐIỂM CHI TIẾT:')
    text = text.replace('✅ ĐIỂM MẠNH', '</div><div class="strengths">✅ ĐIỂM MẠNH')
    text = text.replace('❌ LỖI SAI', '</div><div class="errors">❌ LỖI SAI')
    text = text.replace('💡 GỢI Ý', '</div><div class="suggestions">💡 GỢI Ý')
    
    # Xuống dòng
    text = text.replace('\n', '<br>')
    
    text += '</div>'  # Đóng div cuối cùng
    
    return text

    ##########################################

@app.route("/tam_an")
def tam_an():
    return render_template("chat_tam_an.html")

@app.route("/home")
def home():
    return render_template("menu.html")

@app.route("/enter_nickname")
def enter_nickname():
    return render_template("nickname.html")

@app.route("/start_game", methods=["POST"])
def start_game():
    nickname = request.form["nickname"]
    bai = request.form["bai"]
    session["nickname"] = nickname
    session["bai"] = bai
    return redirect("/game")

@app.route("/game")
def game():
    return render_template("game.html")

@app.route("/get_questions")
def get_questions_quiz():
    import random
    bai = session.get("bai", "bai_1")
    with open("questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get(bai, [])
    random.shuffle(questions)
    for q in questions:
        random.shuffle(q["options"])
    return jsonify(questions[:20])

@app.route("/submit_score", methods=["POST"])
def submit_score():
    nickname = session.get("nickname")
    bai = session.get("bai")
    score = request.json["score"]

    if not nickname:
        return jsonify({"status": "error", "message": "No nickname found"})
    if not bai:
        return jsonify({"status": "error", "message": "No bai found"})

    if not os.path.exists("scores.json"):
        with open("scores.json", "w", encoding="utf-8") as f:
            json.dump([], f)

    with open("scores.json", "r+", encoding="utf-8") as f:
        scores = json.load(f)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        existing = next((s for s in scores if s["nickname"] == nickname and s.get("bai") == bai), None)

        if existing:
            if score > existing["score"]:
                existing["score"] = score
                existing["time"] = now
        else:
            scores.append({
                "nickname": nickname,
                "score": score,
                "time": now,
                "bai": bai
            })
        filtered = [s for s in scores if s.get("bai") == bai]
        top50 = sorted(filtered, key=lambda x: x["score"], reverse=True)[:50]
        others = [s for s in scores if s.get("bai") != bai]
        final_scores = others + top50

        f.seek(0)
        json.dump(final_scores, f, ensure_ascii=False, indent=2)
        f.truncate()

    return jsonify({"status": "ok"})

@app.route("/leaderboard")
def leaderboard():
    bai = session.get("bai")

    if not bai:
        bai = "bai_1"

    if not os.path.exists("scores.json"):
        top5 = []
    else:
        with open("scores.json", "r", encoding="utf-8") as f:
            scores = json.load(f)

        filtered = [s for s in scores if s.get("bai") == bai]
        top5 = sorted(filtered, key=lambda x: x["score"], reverse=True)[:5]

    return render_template("leaderboard.html", players=top5, bai=bai)

###############
@app.route('/dich-vu-y-te')
def dich_vu():
    """Route hiển thị danh sách các cơ sở y tế tại Hà Nội"""
    
    # Dữ liệu các cơ sở y tế
    co_so_y_te = [
        {
            'ten': 'Công ty CP Tham vấn, Nghiên cứu và Tâm lý học Cuộc sống - SHARE',
            'dia_chi': '31 Ngõ 84 Trần Quang Diệu, Quang Trung, Đống Đa, Hà Nội',
            'dien_thoai': '024 22116989',
            'website': 'tuvantamly.com.vn',
            'loai': 'Tư vấn tâm lý'
        },
        {
            'ten': 'Bệnh viện Tâm thần ban ngày Mai Hương',
            'dia_chi': '4 Hồng Mai, Bạch Mai, Hai Bà Trưng, Hà Nội',
            'dien_thoai': '024 3627 5762',
            'website': 'http://www.maihuong.gov.vn/',
            'loai': 'Bệnh viện tâm thần'
        },
        {
            'ten': 'Bệnh viện Tâm thần Hà Nội',
            'dia_chi': 'Ngõ 467 Nguyễn Văn Linh, Sài Đồng, Long Biên, Hà Nội',
            'dien_thoai': '024 3827 6534',
            'website': '',
            'loai': 'Bệnh viện tâm thần'
        },
        {
            'ten': 'Bệnh viện Tâm thần Trung ương I',
            'dia_chi': 'Hòa Bình - Thượng Tín - Hà Nội',
            'dien_thoai': '02433.853.227',
            'website': '',
            'loai': 'Bệnh viện tâm thần'
        },
        {
            'ten': 'Khoa Tâm thần - Bệnh viện Quân Y 103',
            'dia_chi': '261 Phùng Hưng - Hà Đông - Hà Nội',
            'dien_thoai': '',
            'website': '',
            'loai': 'Khoa tâm thần'
        },
        {
            'ten': 'Khoa Tâm bệnh học và Liệu pháp tâm lý, Bệnh viện Việt Pháp Hà Nội',
            'dia_chi': '1 Phương Mai, Phương Mai, Đống Đa, Hà Nội',
            'dien_thoai': '024 3577 1100',
            'website': '',
            'loai': 'Khoa tâm thần'
        },
        {
            'ten': 'Khoa Tâm thần - Bệnh viện Nhi trung ương',
            'dia_chi': '18/879 đường La Thành, Láng Thượng, quận Đống Đa, Hà Nội',
            'dien_thoai': '024 6273 8965 hoặc 024 6273 8964',
            'website': '',
            'loai': 'Khoa tâm thần'
        }
    ]
    
    return render_template('dichvu.html', co_so_y_te=co_so_y_te)


if __name__ == '__main__':
    app.run(debug=True, threaded=True)