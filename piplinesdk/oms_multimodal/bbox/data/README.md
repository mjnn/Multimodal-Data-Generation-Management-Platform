# Bundled OpenCV detector assets

| File | Source | License |
|------|--------|---------|
| `haarcascade_frontalface_default.xml` | [OpenCV](https://github.com/opencv/opencv) `data/haarcascades/` | Apache-2.0 |
| `face_detection_yunet_2023mar.onnx` | [opencv_zoo](https://github.com/opencv/opencv_zoo) YuNet | Apache-2.0 |
| `age_deploy.prototxt` / `gender_deploy.prototxt` | [learnopencv AgeGender](https://github.com/spmallick/learnopencv/tree/master/AgeGender) (Gil Levi nets) | research / tutorial reuse |
| `age_googlenet.onnx` / `gender_googlenet.onnx` | **not bundled** (~24MB each) — downloaded on first use | [onnx/models age_gender](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/age_gender) |
| `age_net.caffemodel` / `gender_net.caffemodel` | **not bundled** (~45MB each) — OpenCV 4 only | Gil Levi AgeGenderDeepLearning |

## Why bundled

- `opencv-python-headless` often ships an empty `cv2/data/` (no Haar XML).
- OpenCV **5.x** removed `CascadeClassifier` from the main package (moved to contrib).
  The SDK falls back to `cv2.FaceDetectorYN` + the YuNet ONNX above.
- OpenCV **5.x** also removed Caffe DNN importers (`readNetFromCaffe`). Face
  gender/age therefore uses **ONNX** GoogleNet weights on OpenCV 5+.

## Face gender / age (OpenCV detector only)

After Haar/YuNet face boxes, the SDK optionally runs age/gender nets
(`BBOX_FACE_ATTRS=1`, default on for local SDK when models are available).

**Backend auto-select**

| OpenCV | Backend | Weights |
|--------|---------|---------|
| 5.x | ONNX (`readNetFromONNX`) | `age_googlenet.onnx` / `gender_googlenet.onnx` |
| 4.x | Caffe (`readNetFromCaffe`) | `age_net.caffemodel` + prototxt (ONNX fallback) |

Force with `BBOX_FACE_ATTRS_BACKEND=onnx|caffe`.

**First-run download** (into this directory) when files are missing and
`BBOX_FACE_ATTRS_AUTO_DOWNLOAD=1` (default):

- Age ONNX: https://media.githubusercontent.com/media/onnx/models/main/validated/vision/body_analysis/age_gender/models/age_googlenet.onnx
- Gender ONNX: https://media.githubusercontent.com/media/onnx/models/main/validated/vision/body_analysis/age_gender/models/gender_googlenet.onnx
- (OpenCV 4) Age Caffe: https://www.dropbox.com/s/xfb20y596869vbb/age_net.caffemodel?dl=1
- (OpenCV 4) Gender Caffe: https://www.dropbox.com/s/iyv483wz7ztr9gh/gender_net.caffemodel?dl=1

Or place the weight files here manually, or set:

```text
BBOX_AGE_ONNX=C:\path\to\age_googlenet.onnx
BBOX_GENDER_ONNX=C:\path\to\gender_googlenet.onnx
# OpenCV 4 only:
BBOX_AGE_MODEL=C:\path\to\age_net.caffemodel
BBOX_GENDER_MODEL=C:\path\to\gender_net.caffemodel
```

If weights are missing, face detection still works; boxes simply omit `gender` /
`age_range` / `age_approx`.

Disable with `BBOX_FACE_ATTRS=0` (HMI: 「人脸属性：性别/年龄」).

Output caption example: `face/female/~28y` (age bucket midpoint).
