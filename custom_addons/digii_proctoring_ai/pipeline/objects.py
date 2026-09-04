# -*- coding: utf-8 -*-
"""
pipeline/objects.py — Detection d'objets suspects avec YOLOv8.

Responsabilite : prendre UNE frame et detecter les objets pertinents
pour la triche via YOLOv8n (modele COCO pre-entraine) :
  - person   -> compter (2eme personne = suspect)
  - cell phone -> telephone visible
  - book     -> papier/notes (approximatif avec COCO)

On ne garde que les classes qui nous interessent, on ignore le reste
(chaise, tasse, etc.).

Comme MediaPipe, le modele YOLO se charge UNE fois et se reutilise.
"""
import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# Classes COCO qui nous interessent -> nom interne.
# Les IDs COCO : 0=person, 67=cell phone, 73=book.
_TARGET_CLASSES = {
    "person": "person",
    "cell phone": "phone",
    "book": "paper",
}


@dataclass
class DetectedObject:
    """Un objet detecte dans une frame."""
    label: str            # "person", "phone", "paper"
    confidence: float
    bbox: tuple           # (x1, y1, x2, y2) en pixels


@dataclass
class ObjectResult:
    """Resultat de la detection d'objets sur une frame."""
    person_count: int = 0
    phone_detected: bool = False
    paper_detected: bool = False
    objects: list = field(default_factory=list)  # list[DetectedObject]


class ObjectDetector:
    """
    Encapsule YOLOv8. Instancier UNE fois, reutiliser.
    """

    def __init__(self, model_path: str = "yolov8n.pt", confidence: float = 0.4):
        # Import ici pour ne pas exiger ultralytics au chargement du module.
        from ultralytics import YOLO
        self.model = YOLO(model_path)  # telecharge auto si absent
        self.confidence = confidence

    def detect(self, image: np.ndarray) -> ObjectResult:
        """Detecte les objets suspects dans une frame BGR."""
        # verbose=False pour ne pas polluer les logs a chaque frame.
        results = self.model(image, conf=self.confidence, verbose=False)

        result = ObjectResult()
        if not results:
            return result

        boxes = results[0].boxes
        names = results[0].names  # dict id -> nom de classe

        for box in boxes:
            cls_id = int(box.cls[0])
            cls_name = names.get(cls_id, "")
            if cls_name not in _TARGET_CLASSES:
                continue  # objet non pertinent, on ignore

            label = _TARGET_CLASSES[cls_name]
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]

            result.objects.append(DetectedObject(
                label=label, confidence=round(conf, 3),
                bbox=(x1, y1, x2, y2),
            ))

            if label == "person":
                result.person_count += 1
            elif label == "phone":
                result.phone_detected = True
            elif label == "paper":
                result.paper_detected = True

        return result
