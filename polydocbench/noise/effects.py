"""Photometric scan effects. Geometry is unchanged; legibility is not guaranteed."""

import math


def sample_effect(name, rng, dpi):
    scale = dpi / 200
    if name == "defocus_blur":
        return {"sigma_pixels": min(12, rng.uniform(1.2, 2.2) * scale)}
    if name == "motion_blur":
        length = min(101, max(1, round(rng.uniform(7, 13) * scale)))
        return {"length_pixels": length if length % 2 else length - 1,
                "angle_degrees": rng.uniform(-60, 60)}
    if name == "sensor_noise":
        return {"sigma": rng.uniform(8, 20), "noise_seed": f"{rng.getrandbits(64):064x}"}
    if name == "faded_ink":
        return {"retained_contrast": rng.uniform(0.25, 0.5)}
    if name == "local_shadow":
        return {"strength": rng.uniform(0.35, 0.65), "center_x": rng.uniform(0.1, 0.9),
                "center_y": rng.uniform(0.1, 0.9), "radius_x": rng.uniform(0.12, 0.35),
                "radius_y": rng.uniform(0.12, 0.35)}
    if name == "bleed_through":
        return {"opacity": rng.uniform(0.12, 0.25), "sigma_pixels": min(12, rng.uniform(0.8, 1.6) * scale),
                "shift_x": min(4096, round(rng.uniform(8, 20) * scale)),
                "shift_y": min(4096, round(rng.uniform(8, 20) * scale)), "source": "mirrored_self_page"}
    raise ValueError(f"Unsupported noise operation: {name}")


def apply_effect(image, name, values):
    import cv2
    import numpy as np

    if name == "defocus_blur":
        return (image.copy() if values["sigma_pixels"] == 0 else
                cv2.GaussianBlur(image, (0, 0), values["sigma_pixels"]))
    if name == "motion_blur":
        length = values["length_pixels"]
        radius = length // 2
        angle = math.radians(values["angle_degrees"])
        dx, dy = round(radius * math.cos(angle)), round(radius * math.sin(angle))
        kernel = np.zeros((length, length), dtype=np.float32)
        cv2.line(kernel, (radius - dx, radius - dy), (radius + dx, radius + dy), 1, 1)
        return cv2.filter2D(image, -1, kernel / kernel.sum())
    if name == "sensor_noise":
        rng = np.random.Generator(np.random.PCG64(int(values["noise_seed"], 16)))
        output = image.astype(float) + rng.normal(0, values["sigma"], image.shape)
    elif name == "faded_ink":
        output = 255 - (255 - image.astype(float)) * values["retained_contrast"]
    elif name == "local_shadow":
        height, width = image.shape[:2]
        y, x = np.ogrid[:height, :width]
        distance = ((x / max(1, width - 1) - values["center_x"]) / values["radius_x"]) ** 2
        distance = distance + ((y / max(1, height - 1) - values["center_y"]) / values["radius_y"]) ** 2
        output = image.astype(float) * (1 - values["strength"] * np.exp(-distance / 2))[..., None]
    else:
        height, width = image.shape[:2]
        reverse = cv2.flip(image, 1)
        if values["sigma_pixels"] > 0:
            reverse = cv2.GaussianBlur(reverse, (0, 0), values["sigma_pixels"])
        reverse = cv2.warpAffine(reverse, np.array([[1, 0, values["shift_x"]], [0, 1, values["shift_y"]]], dtype=float),
                                 (width, height), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        output = image.astype(float) - values["opacity"] * (255 - reverse.astype(float))
    return np.clip(np.rint(output), 0, 255).astype(np.uint8)
