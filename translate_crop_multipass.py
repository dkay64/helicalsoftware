#!/usr/bin/env python3
import cv2
import numpy as np
import math
import argparse
import sys
from tqdm import tqdm

def translate_crop_multipass(input_path: str,
                             output_path: str,
                             pixel_size_um: float,
                             crop_height_px: int,
                             cycles_per_pass: float,
                             deg_per_sec: float = 54.0,
                             down_shift_px: int = 0,
                             image_height_px: int = None):
    # 1) open video to get dimensions
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error: cannot open {input_path}", file=sys.stderr)
        sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS)
    W   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # 2) compute real-world distances
    pixel_size_mm    = pixel_size_um / 1000.0
    video_mm         = H * pixel_size_mm
    window_mm        = crop_height_px * pixel_size_mm
    total_travel_mm  = video_mm + window_mm
    total_travel_px  = crop_height_px + H  # for sanity

    # 3) timing & speed
    time_per_pass    = (360.0 / deg_per_sec) * cycles_per_pass
    velocity_mm_per_s = total_travel_mm / time_per_pass
    print(f"\nTime per pass:         {time_per_pass:.2f} s")
    print(f"{cycles_per_pass} rotation(s) per pass at {deg_per_sec}°/s")
    print(f"Total travel dist.:    {total_travel_mm:.1f} mm ({total_travel_px} px)")
    print(f"Velocity:              {velocity_mm_per_s:.4f} mm/s")
    print(f"Down-shift before return: {down_shift_px} px ({down_shift_px*pixel_size_mm:.3f} mm)\n")

    # 4) reload all frames
    cap = cv2.VideoCapture(input_path)
    frames = []
    while True:
        ret, f = cap.read()
        if not ret: break
        frames.append(f)
    cap.release()
    if not frames:
        print("Error: no frames read", file=sys.stderr)
        sys.exit(1)
    N_in = len(frames)

    # 5) compute pixel-based travel & frame counts
    pad_px          = crop_height_px
    crop_top_start  = pad_px + H
    crop_top_end    = pad_px - crop_height_px + 1
    travel_px       = crop_top_start - crop_top_end

    v_px_per_frame  = (velocity_mm_per_s / pixel_size_mm) / fps
    if v_px_per_frame <= 0:
        print("Error: non-positive shift per frame", file=sys.stderr)
        sys.exit(1)

    n_up_frames   = int(math.ceil(travel_px / v_px_per_frame))
    # after down_shift, remaining px to travel back:
    back_px       = max(0, travel_px - down_shift_px)
    n_down_frames = int(math.ceil(back_px / v_px_per_frame))
    total_frames  = n_up_frames + n_down_frames

    # 6) prepare output
    if image_height_px is None:
        image_height_px = crop_height_px
    out_h_px = max(crop_height_px, image_height_px)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out    = cv2.VideoWriter(output_path, fourcc, fps, (W, out_h_px))
    if not out.isOpened():
        print(f"Error: cannot write {output_path}", file=sys.stderr)
        sys.exit(1)

    padded_H = H + 2 * pad_px

    # 7) process frames: up-pass then down-pass
    for i in tqdm(range(total_frames), desc="Processing", ncols=80):
        frame  = frames[i % N_in]
        padded = np.zeros((padded_H, W, 3), dtype=np.uint8)
        padded[pad_px:pad_px+H] = frame

        if i < n_up_frames:
            # upward translation
            offset   = v_px_per_frame * i
            crop_top = int(round(crop_top_start - offset))
        else:
            # downward translation, after a jump down
            j        = i - n_up_frames
            offset   = v_px_per_frame * j
            crop_top = int(round((crop_top_end + down_shift_px) + offset))

        # clamp into valid range
        crop_top = max(crop_top_end, min(crop_top, crop_top_start))
        window   = padded[crop_top:crop_top + crop_height_px]

        # center in taller frame if needed
        if out_h_px > crop_height_px:
            tp     = (out_h_px - crop_height_px)//2
            canvas = np.zeros((out_h_px, W, 3), dtype=np.uint8)
            canvas[tp:tp+crop_height_px] = window
            out.write(canvas)
        else:
            out.write(window)

    out.release()
    total_time = total_frames / fps
    print(f"\nDone → {output_path}")
    print(f"Total duration: {total_time:.1f}s ({total_frames} frames @ {fps:.2f} FPS)\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Translate-crop a rotating video up & down, with a down-shift before return."
    )
    p.add_argument("input",            help="source .mp4")
    p.add_argument("output",           help="dest .mp4")
    p.add_argument("--pixel_size_um",  type=float, default=50.0,
                   help="pixel size in μm")
    p.add_argument("--crop_height_px", type=int,   required=True,
                   help="height of moving window in px")
    p.add_argument("--cycles_per_pass",type=float, required=True,
                   help="rotations per upward pass")
    p.add_argument("--deg_per_sec",    type=float, default=54.0,
                   help="rotation speed in °/s")
    p.add_argument("--down_shift_px",  type=int,   default=0,
                   help="pixels to jump down at start of return pass")
    p.add_argument("--image_height_px",type=int,   default=None,
                   help="final frame height in px; pads if larger")

    args = p.parse_args()
    translate_crop_multipass(
        args.input,
        args.output,
        pixel_size_um   = args.pixel_size_um,
        crop_height_px  = args.crop_height_px,
        cycles_per_pass = args.cycles_per_pass,
        deg_per_sec     = args.deg_per_sec,
        down_shift_px   = args.down_shift_px,
        image_height_px = args.image_height_px,
    )
