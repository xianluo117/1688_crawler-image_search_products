#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse

from lib.ali1688.ali1688 import Ali1688Upload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="1688 图片上传与以图搜货链接生成")
    parser.add_argument(
        "image",
        nargs="?",
        default="data/down.jpeg",
        help="需要上传的图片路径，默认：data/down.jpeg",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    upload = Ali1688Upload()
    response = upload.upload(filename=args.image)
    response.raise_for_status()

    payload = response.json()
    image_id = payload.get("data", {}).get("imageId", "")
    if not image_id:
        raise RuntimeError("1688 图片上传失败：响应中不存在 imageId")

    print(upload.image_search_url(image_id=image_id))


if __name__ == "__main__":
    main()
