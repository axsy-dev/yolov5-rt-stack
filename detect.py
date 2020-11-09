import time
from pathlib import Path

from numpy import random
import numpy as np

import cv2
import torch

from utils.datasets import LoadImages
from utils.torch_utils import time_synchronized

from utils.general import (
    check_img_size,
    box_xyxy_to_cxcywh, plot_one_box,
    set_logging,
)

from hubconf import yolov5


def load_names(category_path):
    names = []
    with open(category_path, 'r') as f:
        for line in f:
            names.append(line.strip())
    return names


def read_image(img_name, is_half):
    img = cv2.imread(img_name)
    img = np.ascontiguousarray(img, dtype=np.float32)  # uint8 to float32
    img /= 255.0  # 0 - 255 to 0.0 - 1.0
    img = torch.from_numpy(img)
    img = img.permute(2, 0, 1)
    return img


@torch.no_grad()
def inference(model, img_name, device, is_half=False):
    model.eval()
    img = read_image(img_name, is_half)
    img = img.to(device)
    t1 = time_synchronized()
    detections = model([img])
    time_consume = time_synchronized() - t1

    return detections, time_consume


@torch.no_grad()
def overlay_boxes(detections, path, time_consume, args):
    img = cv2.imread(path) if args.save_img else None

    for i, pred in enumerate(detections):  # detections per image
        s = '%g: ' % i if args.webcam else ''
        save_path = Path(args.output_dir).joinpath(Path(path).name)
        txt_path = Path(args.output_dir).joinpath(Path(path).stem)

        if pred is not None and len(pred) > 0:
            # Rescale boxes from img_size to im0 size
            boxes, scores, labels = pred['boxes'].round(), pred['scores'], pred['labels']

            # Print results
            for c in labels.unique():
                n = (labels == c).sum()  # detections per class
                s += '%g %ss, ' % (n, args.names[int(c)])  # add to string

            # Write results
            for xyxy, conf, cls_name in zip(boxes, scores, labels):
                if args.save_txt:  # Write to file
                    # normalized xywh
                    xywh = box_xyxy_to_cxcywh(xyxy).tolist()
                    with open(f'{txt_path}.txt', 'a') as f:
                        f.write(('%g ' * 5 + '\n') % (cls_name, *xywh))  # label format

                if args.save_img:  # Add bbox to image
                    label = '%s %.2f' % (args.names[int(cls_name)], conf)
                    plot_one_box(xyxy, img, label=label, color=args.colors[int(cls_name)], line_thickness=3)

        # Print inference time
        print('%sDone. (%.3fs)' % (s, time_consume))

        # Save results (image with detections)
        if args.save_img and args.mode == 'images':
            cv2.imwrite(str(save_path), img)

    return (boxes.tolist(), scores.tolist(), labels.tolist())


def main(args):
    print(args)
    device = torch.device("cuda") if torch.cuda.is_available() and args.gpu else torch.device("cpu")

    model = yolov5(cfg_path=args.model_cfg, checkpoint_path=args.checkpoint)
    model.eval()
    model = model.to(device)

    args.webcam = (args.input_source.isnumeric() or args.input_source.startswith(
        ('rtsp://', 'rtmp://', 'http://')) or args.input_source.endswith('.txt'))

    # Initialize
    set_logging()

    # half = device.type != 'cpu'  # half precision only supported on CUDA
    is_half = False

    # Load model
    imgsz = check_img_size(args.img_size, s=model.box_head.stride.max())  # check img_size
    if is_half:
        model.half()  # to FP16

    # Set Dataloader
    dataset = LoadImages(args.input_source, img_size=imgsz)
    args.mode = dataset.mode

    # Get names and colors
    args.names = load_names(Path(args.labelmap))
    args.colors = [[random.randint(0, 255) for _ in range(3)] for _ in range(len(args.names))]

    # Run inference
    t0 = time.time()
    img = torch.zeros((3, imgsz, imgsz), device=device)  # init img
    if is_half:
        img = img.half()
    _ = model([img])  # run once

    for data in dataset:
        img_name = data[0]
        model_out, time_consume = inference(model, img_name, device, is_half)

        # Process detections
        _ = overlay_boxes(model_out, img_name, time_consume, args)

    if args.save_txt or args.save_img:
        print(f'Results saved to {args.output_dir}')

    print('Done. (%.3fs)' % (time.time() - t0))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--model_cfg', type=str, default='./models/yolov5s.yaml',
                        help='path where the model cfg in')
    parser.add_argument('--checkpoint', type=str, default='./checkpoints/yolov5/yolov5s.pt',
                        help='path where the model checkpoint in')
    parser.add_argument('--labelmap', type=str, default='./checkpoints/yolov5/coco.names',
                        help='path where the coco category in')
    parser.add_argument('--input_source', type=str, default='./.github/',
                        help='path where the source images in')
    parser.add_argument('--output_dir', type=str, default='./data-bin/output',
                        help='path where to save')
    parser.add_argument('--img_size', type=int, default=416,
                        help='inference size (pixels)')
    parser.add_argument('--conf_thres', type=float, default=0.4,
                        help='object confidence threshold')
    parser.add_argument('--iou_thres', type=float, default=0.5,
                        help='IOU threshold for NMS')
    parser.add_argument('--gpu', action='store_true',
                        help='GPU switch')
    parser.add_argument('--view_img', action='store_true',
                        help='display results')
    parser.add_argument('--save_txt', action='store_true',
                        help='save results to *.txt')
    parser.add_argument('--save_img', action='store_true',
                        help='save image inference results')
    parser.add_argument('--classes', nargs='+', type=int,
                        help='filter by class: --class 0, or --class 0 2 3')
    parser.add_argument('--agnostic_nms', action='store_true',
                        help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true',
                        help='augmented inference')

    args = parser.parse_args()

    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    main(args)