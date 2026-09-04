# -*- coding: utf-8 -*-
"""
pipeline/face.py — Analyse du visage avec MediaPipe.

Responsabilite : prendre UNE frame et en extraire :
  - le visage est-il present ?
  - combien de visages ?
  - orientation de la tete : yaw (gauche/droite), pitch (haut/bas), roll
  - les levres bougent-elles ? (pour croiser avec l'audio)

Le calcul du head pose se fait par solvePnP : on prend quelques
landmarks 3D connus du visage (bout du nez, menton, coins des yeux...)
et on estime l'orientation de la tete face a la camera.

IMPORTANT : MediaPipe se charge une seule fois (objet lourd). On l'isole
dans une classe qu'on instancie une fois et qu'on reutilise pour toutes
les frames.
"""
import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FaceResult:
    """Resultat de l'analyse d'une frame."""
    face_present: bool = False
    face_count: int = 0
    yaw: float = 0.0      # rotation gauche(-)/droite(+) en degres
    pitch: float = 0.0    # rotation haut(-)/bas(+) en degres
    roll: float = 0.0     # inclinaison en degres
    mouth_open: bool = False  # levres ecartees (parle peut-etre)


# Indices des landmarks MediaPipe Face Mesh utilises pour solvePnP.
# Ce sont des points stables du visage.
_LANDMARK_IDS = {
    "nose_tip": 1,
    "chin": 152,
    "left_eye_corner": 33,
    "right_eye_corner": 263,
    "left_mouth": 61,
    "right_mouth": 291,
}

# Modele 3D generique d'un visage (coordonnees approximatives en mm).
# Sert de reference pour estimer l'orientation via solvePnP.
_MODEL_POINTS_3D = np.array([
    (0.0, 0.0, 0.0),           # nose_tip
    (0.0, -63.6, -12.5),       # chin
    (-43.3, 32.7, -26.0),      # left_eye_corner
    (43.3, 32.7, -26.0),       # right_eye_corner
    (-28.9, -28.9, -24.1),     # left_mouth
    (28.9, -28.9, -24.1),      # right_mouth
], dtype=np.float64)

# Landmarks pour detecter l'ouverture de la bouche (levre haute / basse).
_UPPER_LIP = 13
_LOWER_LIP = 14
_MOUTH_OPEN_RATIO = 0.02  # seuil relatif a la taille du visage


class FaceAnalyzer:
    """
    Encapsule MediaPipe Face Mesh. Instancier UNE fois, reutiliser.
    """

    def __init__(self, max_faces: int = 2):
        # Import ici pour que le module se charge meme sans mediapipe
        # installe (utile pour lancer les tests unitaires du reste).
        import mediapipe as mp
        self._mp = mp
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,   # chaque frame est independante
            max_num_faces=max_faces,  # detecter jusqu'a 2 visages
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )

    def analyze(self, image: np.ndarray) -> FaceResult:
        """Analyse une frame BGR et retourne un FaceResult."""
        h, w = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return FaceResult(face_present=False, face_count=0)

        face_count = len(results.multi_face_landmarks)
        # On analyse le premier visage (le candidat principal).
        landmarks = results.multi_face_landmarks[0].landmark

        yaw, pitch, roll = self._estimate_head_pose(landmarks, w, h)
        mouth_open = self._is_mouth_open(landmarks)

        return FaceResult(
            face_present=True,
            face_count=face_count,
            yaw=round(yaw, 1),
            pitch=round(pitch, 1),
            roll=round(roll, 1),
            mouth_open=mouth_open,
        )

    def _estimate_head_pose(self, landmarks, w: int, h: int):
        """
        Estime yaw/pitch/roll via cv2.solvePnP.
        Retourne (yaw, pitch, roll) en degres.
        """
        # Points 2D detectes (en pixels) correspondant au modele 3D.
        image_points = np.array([
            (landmarks[_LANDMARK_IDS["nose_tip"]].x * w,
             landmarks[_LANDMARK_IDS["nose_tip"]].y * h),
            (landmarks[_LANDMARK_IDS["chin"]].x * w,
             landmarks[_LANDMARK_IDS["chin"]].y * h),
            (landmarks[_LANDMARK_IDS["left_eye_corner"]].x * w,
             landmarks[_LANDMARK_IDS["left_eye_corner"]].y * h),
            (landmarks[_LANDMARK_IDS["right_eye_corner"]].x * w,
             landmarks[_LANDMARK_IDS["right_eye_corner"]].y * h),
            (landmarks[_LANDMARK_IDS["left_mouth"]].x * w,
             landmarks[_LANDMARK_IDS["left_mouth"]].y * h),
            (landmarks[_LANDMARK_IDS["right_mouth"]].x * w,
             landmarks[_LANDMARK_IDS["right_mouth"]].y * h),
        ], dtype=np.float64)

        # Matrice camera approximee depuis la resolution (focale = largeur).
        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1],
        ], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1))  # pas de distorsion supposee

        success, rotation_vec, _ = cv2.solvePnP(
            _MODEL_POINTS_3D, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            return 0.0, 0.0, 0.0

        # Convertit le vecteur de rotation en angles d'Euler.
        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        proj_mat = np.hstack((rotation_mat, np.zeros((3, 1))))
        _, _, _, _, _, _, euler = cv2.decomposeProjectionMatrix(proj_mat)

        # euler peut etre de forme (3, 1) selon la version d'OpenCV :
        # on l'aplatit pour obtenir 3 scalaires surs.
        euler_flat = np.asarray(euler, dtype=np.float64).reshape(-1)
        pitch = float(euler_flat[0])
        yaw = float(euler_flat[1])
        roll = float(euler_flat[2])
        # Normalisation des angles dans [-90, 90] pour la lisibilite.
        pitch = self._normalize_angle(pitch)
        yaw = self._normalize_angle(yaw)
        roll = self._normalize_angle(roll)
        return yaw, pitch, roll

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Ramene un angle dans [-90, 90]."""
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        return angle

    def _is_mouth_open(self, landmarks) -> bool:
        """Detecte si les levres sont ecartees (parle peut-etre)."""
        upper = landmarks[_UPPER_LIP]
        lower = landmarks[_LOWER_LIP]
        gap = abs(upper.y - lower.y)
        return gap > _MOUTH_OPEN_RATIO

    def close(self):
        """Libere les ressources MediaPipe."""
        self.face_mesh.close()
