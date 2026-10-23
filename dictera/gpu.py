"""Sonde GPU : CTranslate2 (moteur de faster-whisper) voit-il CUDA, cuBLAS et cuDNN ?

cuBLAS 12 et cuDNN 9 viennent des paquets pip nvidia-cublas-cu12 / nvidia-cudnn-cu12
installés dans l'environnement de Dictera : rien n'est exigé du toolkit CUDA système.
CTranslate2 fournit le point d'entrée cudnn64_9.dll, mais les vraies dictées chargent
les sous-bibliothèques du paquet pip (cudnn_graph, cudnn_heuristic, cudnn_ops — mesuré
en Phase 6 ; un simple préchauffage ne les charge pas). Les dossiers bin doivent être
enregistrés AVANT que CTranslate2 charge ces DLL.

La sonde a deux étages :
  1. statique (probe_gpu) : périphérique CUDA, float16, chargement des DLL, versions ;
  2. réel (Transcriber.warmup) : un premier passage du modèle sur le GPU, qui exécute
     les convolutions de l'encodeur Whisper, donc cuDNN.
"""

import ctypes
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CUBLAS_DLL = "cublas64_12.dll"
CUDNN_DLL = "cudnn64_9.dll"
COMPUTE_TYPE = "float16"
_registered = False


class GpuProbeError(RuntimeError):
    """Échec de la sonde ; le message dit quoi faire."""


@dataclass
class GpuReport:
    device: str = ""
    driver: str = ""
    vram_mib: int = 0
    cuda_devices: int = 0
    compute_type: str = COMPUTE_TYPE
    compute_types: list[str] = field(default_factory=list)
    ctranslate2_version: str = ""
    cublas_path: str = ""
    cudnn_path: str = ""
    cudnn_version: str = ""

    def lines(self) -> list[str]:
        return [
            f"device        : cuda:0 — {self.device or 'nom inconnu'} ({self.vram_mib} Mio, pilote {self.driver or '?'})",
            f"compute type  : {self.compute_type} (supportés : {', '.join(self.compute_types)})",
            f"CTranslate2   : {self.ctranslate2_version}, {self.cuda_devices} périphérique(s) CUDA",
            f"cuBLAS        : {self.cublas_path}",
            f"cuDNN         : {self.cudnn_version} — {self.cudnn_path}",
        ]


def _nvidia_bin_dirs() -> list[Path]:
    dirs = []
    # Application packagée (PyInstaller) : les DLL sont sous _MEIPASS/nvidia/*/bin.
    bases = [getattr(sys, "_MEIPASS", None), *sys.path]
    for base in map(Path, filter(None, bases)):
        nvidia = base / "nvidia"
        if nvidia.is_dir():
            dirs.extend(p for p in nvidia.glob("*/bin") if p.is_dir())
    return dirs


def register_cuda_dlls() -> list[Path]:
    """Rend les DLL cuBLAS/cuDNN des paquets pip visibles par CTranslate2. Idempotent."""
    global _registered
    dirs = _nvidia_bin_dirs()
    if _registered:
        return dirs
    for d in dirs:
        os.add_dll_directory(str(d))
    # CTranslate2 charge cuDNN par LoadLibrary simple, qui ignore add_dll_directory :
    # le PATH du processus doit aussi les contenir, en tête (avant les toolkits CUDA système).
    os.environ["PATH"] = os.pathsep.join([*map(str, dirs), os.environ.get("PATH", "")])
    _registered = True
    return dirs


def _load_dll(name: str) -> tuple[ctypes.CDLL, str]:
    try:
        lib = ctypes.CDLL(name)
    except OSError as e:
        raise FileNotFoundError(name) from e
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(lib._handle), buf, len(buf))
    return lib, buf.value


def _query_nvidia_smi(report: GpuReport) -> None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return
    if out:
        name, driver, mem = (x.strip() for x in out[0].split(","))
        report.device, report.driver, report.vram_mib = name, driver, int(float(mem))


def probe_gpu() -> GpuReport:
    """Étage statique de la sonde. Lève GpuProbeError avec une consigne actionnable."""
    dirs = register_cuda_dlls()
    report = GpuReport()
    _query_nvidia_smi(report)

    try:
        import ctranslate2
    except ImportError as e:
        raise GpuProbeError(
            "CTranslate2 est introuvable. Dans D:\\Dictera, exécutez :\n"
            "  .venv\\Scripts\\python -m pip install -r requirements.txt"
        ) from e
    report.ctranslate2_version = ctranslate2.__version__

    report.cuda_devices = ctranslate2.get_cuda_device_count()
    if report.cuda_devices == 0:
        raise GpuProbeError(
            "Aucun GPU CUDA visible par CTranslate2.\n"
            "  - Vérifiez que « nvidia-smi » affiche la RTX 4070 Ti.\n"
            "  - Installez ou mettez à jour le pilote NVIDIA (Game Ready ou Studio, branche "
            "compatible CUDA 12), puis redémarrez Windows."
        )

    report.compute_types = sorted(ctranslate2.get_supported_compute_types("cuda"))
    if COMPUTE_TYPE not in report.compute_types:
        raise GpuProbeError(
            f"Le GPU ne prend pas en charge {COMPUTE_TYPE} avec CTranslate2 "
            f"(types supportés : {', '.join(report.compute_types)}). Mettez à jour le pilote NVIDIA."
        )

    hint_dirs = "\n".join(f"    {d}" for d in dirs) or "    (aucun dossier nvidia/*/bin trouvé)"
    try:
        _, report.cublas_path = _load_dll(CUBLAS_DLL)
    except FileNotFoundError as e:
        raise GpuProbeError(
            f"cuBLAS 12 introuvable ({CUBLAS_DLL}). Dans D:\\Dictera, exécutez :\n"
            "  .venv\\Scripts\\python -m pip install nvidia-cublas-cu12\n"
            f"Dossiers examinés :\n{hint_dirs}"
        ) from e
    try:
        cudnn, report.cudnn_path = _load_dll(CUDNN_DLL)
    except FileNotFoundError as e:
        raise GpuProbeError(
            f"cuDNN 9 introuvable ({CUDNN_DLL}). Dans D:\\Dictera, exécutez :\n"
            "  .venv\\Scripts\\python -m pip install \"nvidia-cudnn-cu12==9.*\"\n"
            f"Dossiers examinés :\n{hint_dirs}"
        ) from e
    cudnn.cudnnGetVersion.restype = ctypes.c_size_t
    v = cudnn.cudnnGetVersion()  # ex. 92700 -> 9.27.0
    report.cudnn_version = f"{v // 10000}.{v % 10000 // 100}.{v % 100}"

    log.info("Sonde GPU OK : %s", " | ".join(report.lines()))
    return report
