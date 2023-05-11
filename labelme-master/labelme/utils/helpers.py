import numpy as np
import random
# from .qt import QTPoint
import cv2
from qtpy import QtCore
from qtpy.QtCore import Qt
from qtpy.QtCore import QThread
from qtpy import QtGui
from qtpy import QtWidgets
from labelme import PY2
import os
import json
import orjson





coco_classes = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
                'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
                'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
                'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard',
                'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
                'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
                'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard',
                'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase',
                'scissors', 'teddy bear', 'hair drier', 'toothbrush']
# make a list of 12 unique colors as we will use them to draw bounding boxes of different classes in different colors
# so the calor palette will be used to draw bounding boxes of different classes in different colors
# the color pallette should have the famous 12 colors as red, green, blue, yellow, cyan, magenta, white, black, gray, brown, pink, and orange in bgr format
color_palette = [(75, 25, 230),
                 (75, 180, 60),
                 (25, 225, 255),
                 (200, 130, 0),
                 (49, 130, 245),
                 (180, 30, 145),
                 (240, 240, 70),
                 (230, 50, 240),
                 (60, 245, 210),
                 (190, 190, 250),
                 (128, 128, 0),
                 (255, 190, 230),
                 (40, 110, 170),
                 (200, 250, 255),
                 (0, 0, 128),
                 (195, 255, 170)]


"""
Shape Structure:
    A shape is a dictionary with keys (label, points, group_id, shape_type, flags, line_color, fill_color, shape_type).
    A segment is a list of points.
    A point is a list of two coordinates [x, y].
    A group_id is the id of the track that the shape belongs to.
    A class_id is the id of the class that the shape belongs to.
    A class_id = -1 means that the shape does not belong to any class in the coco dataset.
"""



def get_bbox_xyxy(segment):
    
    """
    Summary:
        Get the bounding box of a polygon in format of [xmin, ymin, xmax, ymax].
        
    Args:
        segment: a list of points
        
    Returns:
        bbox: [x, y, w, h]
    """
    
    segment = np.array(segment)
    x0 = np.min(segment[:, 0])
    y0 = np.min(segment[:, 1])
    x1 = np.max(segment[:, 0])
    y1 = np.max(segment[:, 1])
    return [x0, y0, x1, y1]


def addPoints(shape, n):
    
    """
    Summary:
        Add points to a polygon.
        
    Args:
        shape: a list of points
        n: number of points to add
        
    Returns:
        res: a list of points
    """
    
    # calculate number of points to add between each pair of points
    sub = 1.0 * n / (len(shape) - 1) 
    
    # if sub == 0, then n == 0, no need to add points    
    if sub == 0:
        return res
    
    # if sub < 1, then we need to add points between SOME pairs of points not ALL pairs of points
    if sub < 1:
        res = []
        res.append(shape[0])
        flag = True
        for i in range(len(shape) - 1):
            if flag:
                newPoint = [(shape[i][0] + shape[i + 1][0]) / 2, (shape[i][1] + shape[i + 1][1]) / 2]
                res.append(newPoint)
            res.append(shape[i + 1])
            n -= 1
            # check if we still need to add extra points
            if n == 0:
                flag = False
        return res
    
    # if sub > 1, then we add 'toBeAdded' points between every pair of points
    else:
        toBeAdded = int(sub) + 1
        res = []
        res.append(shape[0])
        for i in range(len(shape) - 1):
            dif = [shape[i + 1][0] - shape[i][0],
                    shape[i + 1][1] - shape[i][1]]
            for j in range(1, toBeAdded):
                newPoint = [shape[i][0] + dif[0] * j /
                            toBeAdded, shape[i][1] + dif[1] * j / toBeAdded]
                res.append(newPoint)
            res.append(shape[i + 1])
        # recursive call to check if there are any points to add
        return addPoints(res, n + len(shape) - len(res))


def reducePoints(polygon, n):
    
    """
    Summary:
        Remove points from a polygon.
        
    Args:
        polygon: a list of points
        n: number of points to reduce to
        
    Returns:
        polygon: a list of points
    """
    # if n >= len(polygon), then no need to reduce
    if n >= len(polygon):
        return polygon
    
    # calculate the distance between each point and: 
    # 1- its previous point
    # 2- its next point
    # 3- the middle point between its previous and next points
    # taking the minimum of these distances as the distance of the point
    distances = polygon.copy()
    for i in range(len(polygon)):
        mid = (np.array(polygon[i - 1]) +
                np.array(polygon[(i + 1) % len(polygon)])) / 2
        dif = np.array(polygon[i]) - mid
        dist_mid = np.sqrt(dif[0] * dif[0] + dif[1] * dif[1])

        dif_right = np.array(
            polygon[(i + 1) % len(polygon)]) - np.array(polygon[i])
        dist_right = np.sqrt(
            dif_right[0] * dif_right[0] + dif_right[1] * dif_right[1])

        dif_left = np.array(polygon[i - 1]) - np.array(polygon[i])
        dist_left = np.sqrt(
            dif_left[0] * dif_left[0] + dif_left[1] * dif_left[1])

        distances[i] = min(dist_mid, dist_right, dist_left)
    
    # adding small random values to distances to avoid duplicate minimum distances
    # it will not affect the result
    distances = [distances[i] + random.random()
                    for i in range(len(distances))]
    ratio = 1.0 * n / len(polygon)
    threshold = np.percentile(distances, 100 - ratio * 100)

    i = 0
    while i < len(polygon):
        if distances[i] < threshold:
            polygon[i] = None
            i += 1
        i += 1
    res = [x for x in polygon if x is not None]
    
    # recursive call to check if there are any points to remove
    return reducePoints(res, n)


def handlePoints(polygon, n):
    
    """
    Summary:
        Add or remove points from a polygon.
        
    Args:
        polygon: a list of points
        n: number of points that the polygon should have
        
    Returns:
        polygon: a list of points
    """
    
    # if n == len(polygon), then no need to add or remove points
    if n == len(polygon):
        return polygon
    
    # if n > len(polygon), then we need to add points
    elif n > len(polygon):
        return addPoints(polygon, n - len(polygon))
    
    # if n < len(polygon), then we need to remove points
    else:
        return reducePoints(polygon, n)


def allign(shape1, shape2):
    
    """
    Summary:
        Allign the points of two polygons according to their slopes.
        
    Args:
        shape1: a list of points
        shape2: a list of points
        
    Returns:
        shape1_alligned: a list of points
        shape2_alligned: a list of points
    """
    
    shape1_center = centerOFmass(shape1)
    shape1_org = [[shape1[i][0] - shape1_center[0], shape1[i]
                    [1] - shape1_center[1]] for i in range(len(shape1))]
    shape2_center = centerOFmass(shape2)
    shape2_org = [[shape2[i][0] - shape2_center[0], shape2[i]
                    [1] - shape2_center[1]] for i in range(len(shape2))]

    shape1_slope = np.arctan2(
        np.array(shape1_org)[:, 1], np.array(shape1_org)[:, 0]).tolist()
    shape2_slope = np.arctan2(
        np.array(shape2_org)[:, 1], np.array(shape2_org)[:, 0]).tolist()

    shape1_alligned = []
    shape2_alligned = []

    for i in range(len(shape1_slope)):
        x1 = np.argmax(shape1_slope)
        x2 = np.argmax(shape2_slope)
        shape1_alligned.append(shape1_org[x1])
        shape2_alligned.append(shape2_org[x2])
        shape1_org.pop(x1)
        shape2_org.pop(x2)
        shape1_slope.pop(x1)
        shape2_slope.pop(x2)

    shape1_alligned = [[shape1_alligned[i][0] + shape1_center[0], shape1_alligned[i]
                        [1] + shape1_center[1]] for i in range(len(shape1_alligned))]
    shape2_alligned = [[shape2_alligned[i][0] + shape2_center[0], shape2_alligned[i]
                        [1] + shape2_center[1]] for i in range(len(shape2_alligned))]

    return (shape1_alligned, shape2_alligned)


def centerOFmass(points):
    
    """
    Summary:
        Calculate the center of mass of a polygon.
        
    Args:
        points: a list of points
        
    Returns:
        center: a list of points
    """
    nppoints = np.array(points)
    sumX = np.sum(nppoints[:, 0])
    sumY = np.sum(nppoints[:, 1])
    return [int(sumX / len(points)), int(sumY / len(points))]


def flattener(list_2d):
    
    """
    Summary:
        Flatten a list of QTpoints.
        
    Args:
        list_2d: a list of QTpoints
        
    Returns:
        points: a list of points
    """
    
    points = [(p.x(), p.y()) for p in list_2d]
    points = np.array(points, np.int16).flatten().tolist()
    return points


def mapFrameToTime(frameNumber, fps):
    
    """
    Summary:
        Map a frame number to its time in the video.
        
    Args:
        frameNumber: the frame number
        fps: the frame rate of the video
        
    Returns:
        frameHours: the hours of the frame
        frameMinutes: the minutes of the frame
        frameSeconds: the seconds of the frame
        frameMilliseconds: the milliseconds of the frame
    """
    
    # get the time of the frame
    frameTime = frameNumber / fps
    frameHours = int(frameTime / 3600)
    frameMinutes = int((frameTime - frameHours * 3600) / 60)
    frameSeconds = int(frameTime - frameHours * 3600 - frameMinutes * 60)
    frameMilliseconds = int(
        (frameTime - frameHours * 3600 - frameMinutes * 60 - frameSeconds) * 1000)
    
    # print them in formal time format
    return frameHours, frameMinutes, frameSeconds, frameMilliseconds


def class_name_to_id(class_name):
    
    """
    Summary:
        Map a class name to its id in the coco dataset.
        
    Args:
        class_name: the class name
        
    Returns:
        class_id: the id of the class
    """
    
    try:
        # map from coco_classes(a list of coco class names) to class_id
        return coco_classes.index(class_name)
    except:
        # this means that the class name is not in the coco dataset
        return -1


def compute_iou(box1, box2):
    
    """
    Summary:
        Computes IOU between two bounding boxes.

    Args:
        box1 (list): List of 4 coordinates (xmin, ymin, xmax, ymax) of the first box.
        box2 (list): List of 4 coordinates (xmin, ymin, xmax, ymax) of the second box.

    Returns:
        iou (float): IOU between the two boxes.
    """
    
    # Compute intersection coordinates
    xmin = max(box1[0], box2[0])
    ymin = max(box1[1], box2[1])
    xmax = min(box1[2], box2[2])
    ymax = min(box1[3], box2[3])

    # Compute intersection area
    if xmin < xmax and ymin < ymax:
        intersection_area = (xmax - xmin) * (ymax - ymin)
    else:
        intersection_area = 0

    # Compute union area
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = box1_area + box2_area - intersection_area

    # Compute IOU
    iou = intersection_area / union_area if union_area > 0 else 0

    return iou
    

def match_detections_with_tracks(detections, tracks, iou_threshold=0.5):
    
    """
    Summary:
        Match detections with tracks based on their bounding boxes using IOU threshold.

    Args:
        detections (list): List of detections, each detection is a dictionary with keys (bbox, confidence, class_id)
        tracks (list): List of tracks, each track is a tuple of (bboxes, track_id, class, conf)
        iou_threshold (float): IOU threshold for matching detections with tracks.

    Returns:
        matched_detections (list): List of detections that are matched with tracks, each detection is a dictionary with keys (bbox, confidence, class_id)
        unmatched_detections (list): List of detections that are not matched with any tracks, each detection is a dictionary with keys (bbox, confidence, class_id)
    """
    
    matched_detections = []
    unmatched_detections = []

    # Loop through each detection
    for detection in detections:
        detection_bbox = detection['bbox']
        # Loop through each track
        max_iou = 0
        matched_track = None
        for track in tracks:
            track_bbox = track[0:4]

            # Compute IOU between detection and track
            iou = compute_iou(detection_bbox, track_bbox)

            # Check if IOU is greater than threshold and better than previous matches
            if iou > iou_threshold and iou > max_iou:
                matched_track = track
                max_iou = iou

        # If a track was matched, add detection to matched_detections list and remove the matched track from tracks list
        if matched_track is not None:
            detection['group_id'] = int(matched_track[4])
            matched_detections.append(detection)
            tracks.remove(matched_track)
        else:
            unmatched_detections.append(detection)

    return matched_detections, unmatched_detections


def get_boxes_conf_classids_segments(shapes):
    
    """
    Summary:
        Get bounding boxes, confidences, class ids, and segments from shapes (NOT QT).
        
    Args:
        shapes: a list of shapes
        
    Returns:
        boxes: a list of bounding boxes 
        confidences: a list of confidences
        class_ids: a list of class ids
        segments: a list of segments 
    """
    
    boxes = []
    confidences = []
    class_ids = []
    segments = []
    for s in shapes:
        label = s["label"]
        points = s["points"]
        # points are one dimensional array of x1,y1,x2,y2,x3,y3,x4,y4
        # we will convert it to a 2 dimensional array of points (segment)
        segment = []
        for j in range(0, len(points), 2):
            segment.append([int(points[j]), int(points[j + 1])])
        # if points is empty pass
        # if len(points) == 0:
        #     continue
        segments.append(segment)

        boxes.append(get_bbox_xyxy(segment))
        confidences.append(float(s["content"]))
        class_ids.append(coco_classes.index(
            label)if label in coco_classes else -1)

    return boxes, confidences, class_ids, segments


def convert_qt_shapes_to_shapes(qt_shapes):
    
    """
    Summary:
        Convert QT shapes to shapes.
        
    Args:
        qt_shapes: a list of QT shapes
        
    Returns:
        shapes: a list of shapes
    """
    
    shapes = []
    for s in qt_shapes:
        shapes.append(dict(
            label=s.label.encode("utf-8") if PY2 else s.label,
            # convert points into 1D array
            points=flattener(s.points),
            bbox=get_bbox_xyxy([(p.x(), p.y()) for p in s.points]),
            group_id=s.group_id,
            content=s.content,
            shape_type=s.shape_type,
            flags=s.flags,
        ))
    return shapes


def convert_QT_to_cv(incomingImage):
    
    """
    Summary:
        Convert QT image to cv image MAT format.
        
    Args:
        incomingImage: a QT image
        
    Returns:
        arr: a cv image MAT format
    """

    incomingImage = incomingImage.convertToFormat(4)

    width = incomingImage.width()
    height = incomingImage.height()

    ptr = incomingImage.bits()
    ptr.setsize(incomingImage.byteCount())
    arr = np.array(ptr).reshape(height, width, 4)  # Copies the data
    return arr


def convert_cv_to_qt(cv_img):
    
    """
    Summary:
        Convert cv image to QT image format.
        
    Args:
        cv_img: a cv image
        
    Returns:
        convert_to_Qt_format: a QT image format
    """
    
    rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb_image.shape
    bytes_per_line = ch * w
    convert_to_Qt_format = QtGui.QImage(
        rgb_image.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
    return convert_to_Qt_format


def draw_bb_id(flags, image, x, y, w, h, id, label, color=(0, 0, 255), thickness=1):
    
    """
    Summary:
        Draw bounding box and id on an image (Single id).
        
    Args:
        flags: a dictionary of flags (bbox, id, class)
        image: a cv2 image
        x: x coordinate of the bounding box
        y: y coordinate of the bounding box
        w: width of the bounding box
        h: height of the bounding box
        id: id of the shape
        label: label of the shape (class name)
        color: color of the bounding box
        thickness: thickness of the bounding box
        
    Returns:
        image: a cv2 image
    """
    
    if flags['bbox']:
        image = cv2.rectangle(
            image, (x, y), (x + w, y + h), color, thickness + 1)

    if flags['id'] or flags['class']:
        if flags['id'] and flags['class']:
            text = f'#{id} {label}'
        if flags['id'] and not flags['class']:
            text = f'#{id}'
        if not flags['id'] and flags['class']:
            text = f'{label}'

        if image.shape[0] < 1000:
            fontscale = 0.5
        else:
            fontscale = 0.7
        text_width, text_height = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, fontscale, thickness)[0]
        text_x = x + 10
        text_y = y - 10

        text_background_x1 = x
        text_background_y1 = y - 2 * 10 - text_height

        text_background_x2 = x + 2 * 10 + text_width
        text_background_y2 = y

        # fontscale is proportional to the image size
        cv2.rectangle(
            img=image,
            pt1=(text_background_x1, text_background_y1),
            pt2=(text_background_x2, text_background_y2),
            color=color,
            thickness=cv2.FILLED,
        )
        cv2.putText(
            img=image,
            text=text,
            org=(text_x, text_y),
            fontFace=cv2.FONT_HERSHEY_SIMPLEX,
            fontScale=fontscale,
            color=(0, 0, 0),
            thickness=thickness,
            lineType=cv2.LINE_AA,
        )

    # there is no bbox but there is id or class
    if (not flags['bbox']) and (flags['id'] or flags['class']):
        image = cv2.line(image, (x + int(w / 2), y + int(h / 2)),
                            (x + 50, y - 5), color, thickness + 1)

    return image


def draw_trajectories(trajectories, CurrentFrameIndex, flags, img, shapes):
    
    """
    Summary:
        Draw trajectories on an image.
        
    Args:
        trajectories: a dictionary of trajectories
        CurrentFrameIndex: the current frame index
        flags: a dictionary of flags (traj, mask)
        img: a cv2 image
        shapes: a list of shapes
        
    Returns:
        img: a cv2 image
    """
    
    x = trajectories['length']
    for shape in shapes:
        id = shape["group_id"]
        pts_traj = trajectories['id_' + str(id)][max(
            CurrentFrameIndex - x, 0): CurrentFrameIndex]
        pts_poly = np.array([[x, y] for x, y in zip(
            shape["points"][0::2], shape["points"][1::2])])
        color_poly = trajectories['id_color_' + str(
            id)]

        if flags['mask']:
            original_img = img.copy()
            if pts_poly is not None:
                cv2.fillPoly(img, pts=[pts_poly], color=color_poly)
            alpha = trajectories['alpha']
            img = cv2.addWeighted(original_img, alpha, img, 1 - alpha, 0)
        for i in range(len(pts_traj) - 1, 0, - 1):

            thickness = (len(pts_traj) - i <= 10) * 1 + (len(pts_traj) -
                                                            i <= 20) * 1 + (len(pts_traj) - i <= 30) * 1 + 3
            # max_thickness = 6
            # thickness = max(1, round(i / len(pts_traj) * max_thickness))

            if pts_traj[i - 1] is None or pts_traj[i] is None:
                continue
            if pts_traj[i] == (-1, - 1) or pts_traj[i - 1] == (-1, - 1):
                break

            # color_traj = tuple(int(0.95 * x) for x in color_poly)
            color_traj = color_poly

            if flags['traj']:
                cv2.line(img, pts_traj[i - 1],
                            pts_traj[i], color_traj, thickness)
                if ((len(pts_traj) - 1 - i) % 10 == 0):
                    cv2.circle(img, pts_traj[i], 3, (0, 0, 0), -1)

    return img


def draw_bb_on_image(trajectories, CurrentFrameIndex, flags, nTotalFrames, image, shapes, image_qt_flag=True):
    
    """
    Summary:
        Draw bounding boxes and trajectories on an image (multiple ids).
        
    Args:
        trajectories: a dictionary of trajectories.
        CurrentFrameIndex: the current frame index.
        nTotalFrames: the total number of frames.
        image: a QT image or a cv2 image.
        shapes: a list of shapes.
        image_qt_flag: a flag to indicate if the image is a QT image or a cv2 image.
        
    Returns:
        img: a QT image or a cv2 image.
    """
    
    img = image
    if image_qt_flag:
        img = convert_QT_to_cv(image)

    for shape in shapes:
        id = shape["group_id"]
        label = shape["label"]

        # color calculation
        idx = coco_classes.index(label) if label in coco_classes else -1
        idx = idx % len(color_palette)
        color = color_palette[idx] if idx != -1 else (0, 0, 255)

        (x1, y1, x2, y2) = shape["bbox"]
        x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
        img = draw_bb_id(flags, img, x, y, w, h, id,
                                label, color, thickness=1)
        center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
        try:
            centers_rec = trajectories['id_' + str(id)]
            try:
                (xp, yp) = centers_rec[CurrentFrameIndex - 2]
                (xn, yn) = center
                if (xp == -1 or xn == -1):
                    c = 5 / 0
                r = 0.5
                x = r * xn + (1 - r) * xp
                y = r * yn + (1 - r) * yp
                center = (int(x), int(y))
            except:
                pass
            centers_rec[CurrentFrameIndex - 1] = center
            trajectories['id_' +
                                                    str(id)] = centers_rec
            trajectories['id_color_' +
                                                    str(id)] = color
        except:
            centers_rec = [(-1, - 1)] * int(nTotalFrames)
            centers_rec[CurrentFrameIndex - 1] = center
            trajectories['id_' +
                                                    str(id)] = centers_rec
            trajectories['id_color_' +
                                                    str(id)] = color

    # print(sys.getsizeof(trajectories))

    img = draw_trajectories(trajectories, CurrentFrameIndex, flags, img, shapes)

    if image_qt_flag:
        img = convert_cv_to_qt(img, )

    return img


def SAM_rects_to_boxes(rects):
    
    """
    Summary:
        Convert a list of QT rectangles to a list of bounding boxes.
        
    Args:
        rects: a list of QT rectangles
        
    Returns:
        res: a list of bounding boxes
    """
    
    res = []
    for rect in rects:
        listPOINTS = [min(rect[0].x(), rect[1].x()),
                        min(rect[0].y(), rect[1].y()),
                        max(rect[0].x(), rect[1].x()),
                        max(rect[0].y(), rect[1].y())]
        listPOINTS = [int(round(x)) for x in listPOINTS]
        res.append(listPOINTS)
    if len(res) == 0:
        res = None
    return res


def SAM_points_and_labels_from_coordinates(coordinates):
    
    """
    Summary:
        Convert a list of coordinates to a list of points and a list of labels.
        
    Args:
        coordinates: a list of coordinates
        
    Returns:
        input_points: a list of points
        input_labels: a list of labels
    """
    
    input_points = []
    input_labels = []
    for coordinate in coordinates:
        input_points.append(
            [int(round(coordinate[0])), int(round(coordinate[1]))])
        input_labels.append(coordinate[2])
    if len(input_points) == 0:
        input_points = None
        input_labels = None
    else:
        input_points = np.array(input_points)
        input_labels = np.array(input_labels)

    return input_points, input_labels


def load_objects_from_json__json(json_file_name, nTotalFrames):
    
    """
    Summary:
        Load objects from a json file using json library.
        
    Args:
        json_file_name: the name of the json file
        nTotalFrames: the total number of frames
        
    Returns:
        listObj: a list of objects (each object is a dictionary of a frame with keys (frame_idx, frame_data))
    """
    
    listObj = [{'frame_idx': i + 1, 'frame_data': []}
                for i in range(nTotalFrames)]
    if not os.path.exists(json_file_name):
        with open(json_file_name, 'w') as jf:
            json.dump(listObj, jf,
                        indent=4,
                        separators=(',', ': '))
        jf.close()
    with open(json_file_name, 'r') as jf:
        listObj = json.load(jf)
    jf.close()
    return listObj


def load_objects_to_json__json(json_file_name, listObj):
    
    """
    Summary:
        Load objects to a json file using json library.
        
    Args:
        json_file_name: the name of the json file
        listObj: a list of objects (each object is a dictionary of a frame with keys (frame_idx, frame_data))
        
    Returns:
        None
    """
    
    with open(json_file_name, 'w') as json_file:
        json.dump(listObj, json_file,
                    indent=4,
                    separators=(',', ': '))
    json_file.close()


def load_objects_from_json__orjson(json_file_name, nTotalFrames):
    
    """
    Summary:
        Load objects from a json file using orjson library.
        
    Args:
        json_file_name: the name of the json file
        nTotalFrames: the total number of frames
        
    Returns:
        listObj: a list of objects (each object is a dictionary of a frame with keys (frame_idx, frame_data))
    """
    
    listObj = [{'frame_idx': i + 1, 'frame_data': []}
                for i in range(nTotalFrames)]
    if not os.path.exists(json_file_name):
        with open(json_file_name, "wb") as jf:
            jf.write(orjson.dumps(listObj))
        jf.close()
    with open(json_file_name, "rb") as jf:
        listObj = orjson.loads(jf.read())
    jf.close()
    return listObj


def load_objects_to_json__orjson(json_file_name, listObj):
    
    """
    Summary:
        Load objects to a json file using orjson library.
        
    Args:
        json_file_name: the name of the json file
        listObj: a list of objects (each object is a dictionary of a frame with keys (frame_idx, frame_data))
        
    Returns:
        None
    """
    
    with open(json_file_name, "wb") as jf:
        jf.write(orjson.dumps(listObj, option=orjson.OPT_INDENT_2))
    jf.close()









# GUI functions

def OKmsgBox(title, text):
    
    """
    Summary:
        Show an OK message box.
        
    Args:
        title: the title of the message box
        text: the text of the message box
        
    Returns:
        msgBox.exec_(): the result of the message box
    """
    
    msgBox = QtWidgets.QMessageBox()
    msgBox.setIcon(QtWidgets.QMessageBox.Information)
    msgBox.setText(text)
    msgBox.setWindowTitle(title)
    msgBox.setStandardButtons(QtWidgets.QMessageBox.Ok)
    return msgBox.exec_()


def editLabel_idChanged_GUI(config):
    
    """
    Summary:
        Show a dialog to choose the edit options when the id of a shape is changed.
        (Edit only this frame or Edit all frames with this ID)
        
    Args:
        config: a dictionary of configurations
        
    Returns:
        result: the result of the dialog
        config: the updated dictionary of configurations
    """
    
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Choose Edit Options")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.resize(250, 100)

    layout = QtWidgets.QVBoxLayout()

    label = QtWidgets.QLabel("Choose Edit Options")
    layout.addWidget(label)

    only = QtWidgets.QRadioButton("Edit only this frame")
    all = QtWidgets.QRadioButton("Edit all frames with this ID")

    if config['EditDefault'] == 'Edit only this frame':
        only.toggle()
    if config['EditDefault'] == 'Edit all frames with this ID':
        all.toggle()

    only.toggled.connect(lambda: config.update(
        {'EditDefault': 'Edit only this frame'}))
    all.toggled.connect(lambda: config.update(
        {'EditDefault': 'Edit all frames with this ID'}))

    layout.addWidget(only)
    layout.addWidget(all)

    buttonBox = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok)
    buttonBox.accepted.connect(dialog.accept)
    layout.addWidget(buttonBox)
    dialog.setLayout(layout)
    result = dialog.exec_()
    return result, config


def interpolationOptions_GUI(config):
    
    """
    Summary:
        Show a dialog to choose the interpolation options.
        (   interpolate only missed frames between detected frames, 
            interpolate all frames between your KEY frames, 
            interpolate ALL frames with SAM (more precision, more time) )
            
    Args:
        config: a dictionary of configurations
        
    Returns:
        result: the result of the dialog
        config: the updated dictionary of configurations
    """
    
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Choose Interpolation Options")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.resize(250, 100)

    layout = QtWidgets.QVBoxLayout()

    label = QtWidgets.QLabel("Choose Interpolation Options")
    layout.addWidget(label)

    only_missed = QtWidgets.QRadioButton(
        "interpolate only missed frames between detected frames")
    only_edited = QtWidgets.QRadioButton(
        "interpolate all frames between your KEY frames")
    with_sam = QtWidgets.QRadioButton(
        "interpolate ALL frames with SAM (more precision, more time)")

    if config['interpolationDefault'] == 'interpolate only missed frames between detected frames':
        only_missed.toggle()
    if config['interpolationDefault'] == 'interpolate all frames between your KEY frames':
        only_edited.toggle()
    if config['interpolationDefault'] == 'interpolate ALL frames with SAM (more precision, more time)':
        with_sam.toggle()

    only_missed.toggled.connect(lambda: config.update(
        {'interpolationDefault': 'interpolate only missed frames between detected frames'}))
    only_edited.toggled.connect(lambda: config.update(
        {'interpolationDefault': 'interpolate all frames between your KEY frames'}))
    with_sam.toggled.connect(lambda: config.update(
        {'interpolationDefault': 'interpolate ALL frames with SAM (more precision, more time)'}))

    layout.addWidget(only_missed)
    layout.addWidget(only_edited)
    layout.addWidget(with_sam)

    buttonBox = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok)
    buttonBox.accepted.connect(dialog.accept)
    layout.addWidget(buttonBox)
    dialog.setLayout(layout)
    result = dialog.exec_()
    
    return result, config


def exportData_GUI():
    
    """
    Summary:
        Show a dialog to choose the export options in video mode.
        (COCO Format (Detection / Segmentation), MOT Format (Tracking))
        
    Args:
        None
        
    Returns:
        result: the result of the dialog
        coco_radio.isChecked(): a flag to indicate if the COCO Format is checked
        mot_radio.isChecked(): a flag to indicate if the MOT Format is checked
    """
    
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Choose Export Options")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.resize(250, 100)

    layout = QtWidgets.QVBoxLayout()

    label = QtWidgets.QLabel("Choose Export Options")
    layout.addWidget(label)

    # Create a button group to hold the radio buttons
    button_group = QtWidgets.QButtonGroup()

    # Create the radio buttons and add them to the button group
    coco_radio = QtWidgets.QRadioButton(
        "COCO Format (Detection / Segmentation)")
    mot_radio = QtWidgets.QRadioButton("MOT Format (Tracking)")
    button_group.addButton(coco_radio)
    button_group.addButton(mot_radio)

    # Add the radio buttons to the layout
    layout.addWidget(coco_radio)
    layout.addWidget(mot_radio)

    buttonBox = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttonBox.accepted.connect(dialog.accept)
    buttonBox.rejected.connect(dialog.reject)

    layout.addWidget(buttonBox)

    dialog.setLayout(layout)

    result = dialog.exec_()
    
    return result, coco_radio.isChecked(), mot_radio.isChecked()


def deleteSelectedShape_GUI(TOTAL_VIDEO_FRAMES, INDEX_OF_CURRENT_FRAME, config):
    
    """
    Summary:
        Show a dialog to choose the deletion options.
        (   this frame and previous frames,
            this frame and next frames,
            across all frames (previous and next),
            this frame only,
            in a specific range of frames           )
            
    Args:
        TOTAL_VIDEO_FRAMES: the total number of frames
        config: a dictionary of configurations
        
    Returns:
        result: the result of the dialog
        config: the updated dictionary of configurations
        fromFrameVAL: the start frame of the deletion range
        toFrameVAL: the end frame of the deletion range
    """
    
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Choose Deletion Options")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.resize(250, 100)

    layout = QtWidgets.QVBoxLayout()

    label = QtWidgets.QLabel("Choose Deletion Options")
    layout.addWidget(label)

    prev = QtWidgets.QRadioButton("this frame and previous frames")
    next = QtWidgets.QRadioButton("this frame and next frames")
    all = QtWidgets.QRadioButton(
        "across all frames (previous and next)")
    only = QtWidgets.QRadioButton("this frame only")

    from_to = QtWidgets.QRadioButton(
        "in a specific range of frames")
    from_frame = QtWidgets.QSpinBox()
    to_frame = QtWidgets.QSpinBox()
    from_frame.setRange(1, TOTAL_VIDEO_FRAMES)
    to_frame.setRange(1, TOTAL_VIDEO_FRAMES)
    from_frame.valueChanged.connect(lambda: from_to.toggle())
    to_frame.valueChanged.connect(lambda: from_to.toggle())

    if config['deleteDefault'] == 'this frame and previous frames':
        prev.toggle()
    if config['deleteDefault'] == 'this frame and next frames':
        next.toggle()
    if config['deleteDefault'] == 'across all frames (previous and next)':
        all.toggle()
    if config['deleteDefault'] == 'this frame only':
        only.toggle()
    if config['deleteDefault'] == 'in a specific range of frames':
        from_to.toggle()

    prev.toggled.connect(lambda: config.update(
        {'deleteDefault': 'this frame and previous frames'}))
    next.toggled.connect(lambda: config.update(
        {'deleteDefault': 'this frame and next frames'}))
    all.toggled.connect(lambda: config.update(
        {'deleteDefault': 'across all frames (previous and next)'}))
    only.toggled.connect(lambda: config.update(
        {'deleteDefault': 'this frame only'}))
    from_to.toggled.connect(lambda: config.update(
        {'deleteDefault': 'in a specific range of frames'}))

    layout.addWidget(only)
    layout.addWidget(prev)
    layout.addWidget(next)
    layout.addWidget(all)
    layout.addWidget(from_to)
    layout.addWidget(from_frame)
    layout.addWidget(to_frame)

    buttonBox = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok)
    buttonBox.accepted.connect(dialog.accept)
    layout.addWidget(buttonBox)
    dialog.setLayout(layout)
    result = dialog.exec_()
    
    mode = config['deleteDefault']
    fromFrameVAL = from_frame.value() 
    toFrameVAL  = to_frame.value()
    
    if mode == 'this frame and previous frames':
        toFrameVAL = INDEX_OF_CURRENT_FRAME
        fromFrameVAL = 1
    elif mode == 'this frame and next frames':
        toFrameVAL = TOTAL_VIDEO_FRAMES
        fromFrameVAL = INDEX_OF_CURRENT_FRAME
    elif mode == 'this frame only':
        toFrameVAL = INDEX_OF_CURRENT_FRAME
        fromFrameVAL = INDEX_OF_CURRENT_FRAME
    elif mode == 'across all frames (previous and next)':
        toFrameVAL = TOTAL_VIDEO_FRAMES
        fromFrameVAL = 1
    
    return result, config, fromFrameVAL, toFrameVAL














