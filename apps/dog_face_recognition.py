from flask import Blueprint, jsonify, request
import dlib
import imutils
from imutils import face_utils
import cv2
import face_recognition
from database import engine
import pandas as pd
import pymysql
import numpy as np

recognition_dog = Blueprint("recognition_dog", __name__, url_prefix="/dogs")


face_landmark_detector_path = 'dataset/dogHeadDetector.dat'
face_landmark_predictor_path = 'dataset/dogLandmarkDetector.dat'
detector =dlib.cnn_face_detection_model_v1(face_landmark_detector_path)
predictor=dlib.shape_predictor(face_landmark_predictor_path)

def find_face(input_image, size=None, debug=False):
    image = input_image.copy()

    if size:
        image = imutils.resize(image, width=size)

    gray_image= cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dets = detector(gray_image, 1)

    #print('Found {} faces. '.format(len(dets)))

    for (i, det) in enumerate(dets):
        shape = predictor(image, det.rect) #얼굴 영역의 얼굴 랜드마크 결정
        shape = face_utils.shape_to_np(shape) # 랜드마크(x,y) 좌표를 NumPy Array로 변환

        # dlib의 사각형을 OpenCV bounding box로 변환(x, y, w, h)
        (x, y , w, h) = face_utils.rect_to_bb(det.rect)

#랜드마크 그리기
#        if debug:
#            for(i, (x,y)) in enumerate(shape):
#                cv2.circle(image, (x,y), int(image.shape[1]/250), (0, 0, 255), -1)

def _trim_css_to_bounds(css, image_shape):
    return max(css[0], 0), min(css[1], image_shape[1]), min(css[2], image_shape[0]), max(css[3], 0)


def _rect_to_css(rect):
    return rect.top(), rect.right(), rect.bottom(), rect.left()


def _raw_face_locations(img, number_of_times_to_upsample=1):
    return detector(img, number_of_times_to_upsample)


def face_locations(img, number_of_times_to_upsample=1):
    return [_trim_css_to_bounds(_rect_to_css(face.rect), img.shape) for face in _raw_face_locations(img, number_of_times_to_upsample)]

#얼굴 특징 검출
@recognition_dog.route('/recognition', methods=['POST'])
def recognize_dog():
    input_image = np.fromfile(request.files['file'], np.uint8)#request.files['file'] #.stream.read() #이미지파일 받아오기
    print(input_image)
    face_image = cv2.imdecode(input_image, cv2.COLOR_BGR2RGB)
    det_locations = face_locations(face_image, 1)
    try:
        face_encoding = face_recognition.face_encodings(face_image, det_locations)[0]
        face_encoding = face_encoding.tolist()
    except:
        face_encoding = []

    data= {'encoding' : face_encoding}
    return jsonify(data)


#얼굴 유사도 분석, 유사한 이미지를 포함한 게시글 추천
@recognition_dog.route('/similarity', methods=['GET'])
def compare_dog():
    postid = request.args.get('postid')

    related_post = [] #상위 6개 유사 이미지의 게시글 id

#같은 강아지 종의 대표 이미지의 encoding 값 비교, 유사한 이미지 분석
    conn = engine.raw_connection()
    sql_post = f"select * from post_entity where id='{postid}'"
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute(sql_post)
    post = cursor.fetchall() #list 반환
    #print(post)
    if (post.__sizeof__() == 0): data = None
    else:
        post=post[0]
        post_category = post.get('post_category')
        if(post_category) == 0: post_category =1
        else: post_category =0
        sql_breed = f"select post.id, post_category, breed, encoding, title, username, url " \
                    f"from post_entity as post " \
                    f"left join user_entity as user on post.user_id = user.id " \
                    f"left join post_image_entity as image on post.id=image.post_id " \
                    f"group by post.id " \
                    f"having breed='{post.get('breed')}' and post.id !='{post.get('id')}' and post.post_category = {post_category} and post.encoding != '[]'"
        breeds_post = pd.read_sql(sql_breed, con=conn) #.values.tolist()
        #print(list(breeds_post.columns))
        #데이터베이스에서 같은 강아지 종의 이미지 게시글 조회, 모두 가져오기{postid, encoding}

        #현재 게시글 이미지의 encoding 값과 같은 종 리스트의 encoding 값을 유사도 비교

        #print(type(post.get('encoding')))
        encoding = post.get('encoding')
        if(encoding == "[]") :
            if len(breeds_post) == 0:
                print(len(breeds_post))
                related_post = []
            elif len(breeds_post) < 6:
                print(len(breeds_post))
                for i in range(len(breeds_post)):
                    related_post.append(breeds_post.iloc[i].loc[['id', 'post_category', 'title', 'username', 'url']].to_dict())
            else:
                print(len(breeds_post))
                for i in range(6):
                    related_post.append(breeds_post.iloc[i].loc[['id', 'post_category', 'title', 'username', 'url']].to_dict())

        else:

            encoding =encoding[1:len(encoding)-1].split(',')
            encoding = [float(val) for val in encoding]
            #print(encoding)
            encoding = np.array(encoding)

            #breeds_post_id = breeds_post['id'].tolist()
            breeds_post_encoding = breeds_post['encoding'].tolist()
            #print(breeds_post)
            for index, b in enumerate(breeds_post_encoding):
                print(type(b))
                b = b[1:len(b)-1].split(',')
                b = [float(val) for val in b]
                breeds_post_encoding[index] = b


            #print(type(breeds_post))
            #print(breeds_post[0])

            matches = face_recognition.compare_faces(breeds_post_encoding, encoding, tolerance=0.5) #bool 리스트 반환
            face_distances = face_recognition.face_distance(breeds_post_encoding, encoding) #유사도 거리 비교

            sorted_match_index = np.argsort(face_distances)[::-1] #np.argsort: 배열 정렬해 인덱스값 반환
            for index in sorted_match_index:
                if matches[index]:
                    related_post.append(breeds_post.iloc[index].loc[['id', 'post_category','title', 'username','url']].to_dict())
                    if(len(related_post) == 6): break #유사도 상위 6개 반환

        data = {'data' : related_post} #id, post_category, title, username, url 반환(id: postid, url: 이미지 url)
    return jsonify(data)