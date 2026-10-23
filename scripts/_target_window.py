"""Fenêtres de test pour test_phase3.py (processus séparé, comme une vraie appli cible).

Deux fenêtres avec chacune un champ texte : « Cible » (où la dictée doit arriver) et
« Autre fenêtre » (qui prend le focus pendant la dictée). Protocole sur stdin/stdout :
au démarrage, une ligne JSON {"target": hwnd, "other": hwnd} ; puis « dump » renvoie
{"target": texte, "other": texte} ; « quit » ferme tout.
"""

import json
import sys
import threading
import tkinter as tk


def main() -> None:
    root = tk.Tk()
    root.title("Dictera — Cible")
    root.geometry("560x200+200+200")
    target_text = tk.Text(root, font=("Segoe UI", 11), wrap="word")
    target_text.pack(fill="both", expand=True)

    other = tk.Toplevel(root)
    other.title("Dictera — Autre fenêtre")
    other.geometry("560x200+300+460")
    other_text = tk.Text(other, font=("Segoe UI", 11), wrap="word")
    other_text.pack(fill="both", expand=True)

    root.update()
    target_text.focus_set()
    other_text.focus_set()  # Tk mémorise le contrôle focalisé de chaque fenêtre
    root.update()

    def emit(obj: dict) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    emit({"target": int(root.wm_frame(), 16), "other": int(other.wm_frame(), 16)})

    def dump() -> None:
        emit({"target": target_text.get("1.0", "end-1c"), "other": other_text.get("1.0", "end-1c")})

    def read_stdin() -> None:
        for line in sys.stdin:
            cmd = line.strip()
            if cmd == "dump":
                root.after(0, dump)
            elif cmd == "quit":
                break
        root.after(0, root.destroy)

    threading.Thread(target=read_stdin, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
