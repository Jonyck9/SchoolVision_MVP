import sys
import sqlite3
import threading
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QFrame,
    QGridLayout, QDialog, QFormLayout, QLineEdit, QMessageBox,
    QSplitter, QInputDialog
)

APP_DIR = Path.home() / ".schoolvision"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "schoolvision.db"


def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("""
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS cameras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            location TEXT DEFAULT '',
            rtsp_url TEXT DEFAULT '',
            FOREIGN KEY(school_id) REFERENCES schools(id) ON DELETE CASCADE
        )
    """)
    count = con.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    if count == 0:
        con.executemany(
            "INSERT INTO schools(name) VALUES (?)",
            [(f"{n}-я школа",) for n in range(1, 31)]
        )
    con.commit()
    return con


class CameraDialog(QDialog):
    def __init__(self, parent=None, camera=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить камеру" if camera is None else "Изменить камеру")
        self.setMinimumWidth(500)
        self.name_edit = QLineEdit(camera["name"] if camera else "")
        self.location_edit = QLineEdit(camera["location"] if camera else "")
        self.url_edit = QLineEdit(camera["rtsp_url"] if camera else "")
        self.url_edit.setPlaceholderText("rtsp://... (вставьте полный адрес из VLC)")
        self.url_edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        form = QFormLayout()
        form.addRow("Название камеры:", self.name_edit)
        form.addRow("Место установки:", self.location_edit)
        form.addRow("RTSP-адрес:", self.url_edit)
        note = QLabel(
            "Вставьте полный RTSP-адрес, который сработал в VLC. Адрес может содержать пароль; "
            "он будет сохранён только в локальной базе на этом компьютере. Не отправляйте его другим людям."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #a16207;")
        buttons = QHBoxLayout()
        save = QPushButton("Сохранить")
        cancel = QPushButton("Отмена")
        save.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(buttons)

    def values(self):
        return {
            "name": self.name_edit.text().strip(),
            "location": self.location_edit.text().strip(),
            "rtsp_url": self.url_edit.text().strip()
        }


class RtspWorker(QThread):
    frame_ready = Signal(QImage)
    status_changed = Signal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        self.status_changed.emit("Подключение к RTSP…")
        try:
            cap = cv2.VideoCapture()
            # These options are supported by recent OpenCV FFmpeg builds.
            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
            except Exception:
                pass
            opened = cap.open(self.url, cv2.CAP_FFMPEG)
            if not opened or not cap.isOpened():
                cap.release()
                self.status_changed.emit("Не удалось открыть поток. Проверьте RTSP-адрес и доступность камеры.")
                return

            self.status_changed.emit("● Видео подключено")
            failures = 0
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 20:
                        self.status_changed.emit("Поток прерван. Проверьте сеть и RTSP-адрес.")
                        break
                    self.msleep(100)
                    continue
                failures = 0
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, channels = frame.shape
                image = QImage(frame.data, w, h, channels * w, QImage.Format_RGB888).copy()
                self.frame_ready.emit(image)
                self.msleep(1)
            cap.release()
        except Exception as exc:
            self.status_changed.emit(f"Ошибка видеопотока: {exc}")


class SchoolVision(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SchoolVision — видеонаблюдение школ")
        self.resize(1180, 760)
        self.current_school_id = None
        self.current_school_name = ""
        self.camera_workers = {}
        self.camera_screens = {}
        self.camera_status_labels = {}

        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)
        left = QFrame()
        left.setMinimumWidth(250)
        left.setMaximumWidth(330)
        left_layout = QVBoxLayout(left)
        title = QLabel("SCHOOLVISION")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Единая система видеонаблюдения")
        subtitle.setStyleSheet("color: #64748b;")
        self.school_search = QLineEdit()
        self.school_search.setPlaceholderText("Поиск школы...")
        self.school_list = QListWidget()
        self.school_search.textChanged.connect(self.filter_schools)
        self.school_list.currentItemChanged.connect(self.on_school_selected)
        add_school_btn = QPushButton("+ Добавить школу")
        add_school_btn.clicked.connect(self.add_school)
        left_layout.addWidget(title)
        left_layout.addWidget(subtitle)
        left_layout.addSpacing(10)
        left_layout.addWidget(self.school_search)
        left_layout.addWidget(self.school_list, 1)
        left_layout.addWidget(add_school_btn)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        top = QHBoxLayout()
        self.heading = QLabel("Выберите школу")
        self.heading.setStyleSheet("font-size: 24px; font-weight: 700;")
        self.school_meta = QLabel("30 школ в базе")
        self.school_meta.setStyleSheet("color: #64748b;")
        top_left = QVBoxLayout()
        top_left.addWidget(self.heading)
        top_left.addWidget(self.school_meta)
        top.addLayout(top_left, 1)
        self.add_camera_btn = QPushButton("+ Добавить камеру")
        self.add_camera_btn.clicked.connect(self.add_camera)
        self.add_camera_btn.setEnabled(False)
        top.addWidget(self.add_camera_btn, alignment=Qt.AlignTop)
        right_layout.addLayout(top)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 10, 0, 0)
        self.grid.setSpacing(12)
        right_layout.addWidget(self.grid_host, 1)

        self.footer = QLabel(
            "RTSP-видео: добавьте камеру и вставьте полный адрес потока, который работает в VLC. "
            "Для камер в других школах позже потребуется защищённое удалённое подключение."
        )
        self.footer.setWordWrap(True)
        self.footer.setStyleSheet("color: #64748b; padding: 8px; background: #f1f5f9; border-radius: 8px;")
        right_layout.addWidget(self.footer)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([290, 880])
        outer.addWidget(splitter)
        self.setCentralWidget(root)

        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f8fafc; color: #0f172a; font-family: Segoe UI, Arial; font-size: 13px; }
            QLineEdit, QListWidget { background: white; border: 1px solid #cbd5e1; border-radius: 7px; padding: 7px; }
            QListWidget::item { padding: 10px; border-radius: 5px; }
            QListWidget::item:selected { background: #dbeafe; color: #1d4ed8; }
            QPushButton { background: #2563eb; color: white; border: none; border-radius: 7px; padding: 9px 12px; font-weight: 600; }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:disabled { background: #94a3b8; }
        """)
        self.refresh_schools(select_first=True)

    def stop_all_workers(self):
        workers = list(self.camera_workers.values())
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.wait(4500)
        self.camera_workers.clear()
        self.camera_screens.clear()
        self.camera_status_labels.clear()

    def refresh_schools(self, select_first=False):
        current_id = self.current_school_id
        self.school_list.blockSignals(True)
        self.school_list.clear()
        con = db_connect()
        rows = con.execute("SELECT id, name FROM schools ORDER BY name").fetchall()
        con.close()
        for school_id, name in rows:
            item = QListWidgetItem("🏫  " + name)
            item.setData(Qt.UserRole, school_id)
            item.setData(Qt.UserRole + 1, name)
            self.school_list.addItem(item)
            if school_id == current_id:
                self.school_list.setCurrentItem(item)
        self.school_list.blockSignals(False)
        self.filter_schools(self.school_search.text())
        if select_first and self.school_list.count():
            self.school_list.setCurrentRow(0)
        elif current_id is not None:
            for i in range(self.school_list.count()):
                item = self.school_list.item(i)
                if item.data(Qt.UserRole) == current_id:
                    self.school_list.setCurrentItem(item)
                    break

    def filter_schools(self, text):
        for i in range(self.school_list.count()):
            item = self.school_list.item(i)
            item.setHidden(text.lower() not in item.data(Qt.UserRole + 1).lower())

    def on_school_selected(self, current, previous=None):
        if not current:
            return
        self.current_school_id = current.data(Qt.UserRole)
        self.current_school_name = current.data(Qt.UserRole + 1)
        self.heading.setText(self.current_school_name)
        self.add_camera_btn.setEnabled(True)
        self.render_cameras()

    def clear_grid(self):
        self.stop_all_workers()
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_cameras(self):
        self.clear_grid()
        if self.current_school_id is None:
            return
        con = db_connect()
        rows = con.execute(
            "SELECT id, name, location, rtsp_url FROM cameras WHERE school_id=? ORDER BY id",
            (self.current_school_id,)
        ).fetchall()
        con.close()
        self.school_meta.setText(f"{len(rows)} камер(ы) в списке")
        if not rows:
            empty = QLabel("Для этой школы пока нет камер.\nНажмите «Добавить камеру», чтобы создать первую.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #64748b; background: white; border: 1px dashed #cbd5e1; border-radius: 12px; padding: 40px;")
            self.grid.addWidget(empty, 0, 0, 1, 2)
            return
        for index, (camera_id, name, location, url) in enumerate(rows):
            card = QFrame()
            card.setStyleSheet("QFrame { background: #0f172a; border-radius: 12px; } QLabel { color: white; }")
            card_layout = QVBoxLayout(card)
            screen = QLabel("▶\n\nНАЖМИТЕ «ЗАПУСТИТЬ»")
            screen.setAlignment(Qt.AlignCenter)
            screen.setMinimumSize(300, 170)
            screen.setStyleSheet("font-size: 15px; color: #94a3b8; background: #020617; border-radius: 8px;")
            screen.setScaledContents(False)
            self.camera_screens[camera_id] = screen
            cam_title = QLabel(name)
            cam_title.setStyleSheet("font-size: 15px; font-weight: 700;")
            cam_location = QLabel(location or "Место установки не указано")
            cam_location.setStyleSheet("color: #cbd5e1;")
            state = QLabel("● RTSP настроен" if url else "● Укажите RTSP-адрес в настройках")
            state.setStyleSheet("color: #86efac;" if url else "color: #fcd34d;")
            self.camera_status_labels[camera_id] = state

            start_btn = QPushButton("▶ Запустить видео")
            start_btn.setEnabled(bool(url))
            start_btn.clicked.connect(lambda checked=False, cid=camera_id, rt=url: self.start_camera(cid, rt))
            stop_btn = QPushButton("■ Остановить")
            stop_btn.setStyleSheet("background: #475569;")
            stop_btn.clicked.connect(lambda checked=False, cid=camera_id: self.stop_camera(cid))
            edit_btn = QPushButton("Настроить")
            edit_btn.setStyleSheet("background: #475569;")
            edit_btn.clicked.connect(lambda checked=False, cid=camera_id, nm=name, loc=location, rt=url: self.edit_camera(cid, nm, loc, rt))
            delete_btn = QPushButton("Удалить")
            delete_btn.setStyleSheet("background: #475569;")
            delete_btn.clicked.connect(lambda checked=False, cid=camera_id, nm=name: self.delete_camera(cid, nm))
            actions = QHBoxLayout()
            actions.addWidget(start_btn)
            actions.addWidget(stop_btn)
            actions.addWidget(edit_btn)
            actions.addWidget(delete_btn)
            card_layout.addWidget(screen, 1)
            card_layout.addWidget(cam_title)
            card_layout.addWidget(cam_location)
            card_layout.addWidget(state)
            card_layout.addLayout(actions)
            self.grid.addWidget(card, index // 2, index % 2)

    def start_camera(self, camera_id, url):
        if not url:
            QMessageBox.warning(self, "Нет RTSP-адреса", "Нажмите «Настроить» и укажите полный RTSP-адрес.")
            return
        self.stop_camera(camera_id)
        screen = self.camera_screens.get(camera_id)
        status = self.camera_status_labels.get(camera_id)
        if screen:
            screen.setText("Подключение к камере…")
            screen.setPixmap(QPixmap())
        worker = RtspWorker(url, self)
        worker.frame_ready.connect(lambda image, cid=camera_id: self.show_frame(cid, image))
        worker.status_changed.connect(lambda message, label=status: label.setText(message) if label else None)
        worker.finished.connect(lambda cid=camera_id: self.camera_workers.pop(cid, None))
        self.camera_workers[camera_id] = worker
        worker.start()

    def show_frame(self, camera_id, image):
        screen = self.camera_screens.get(camera_id)
        if screen and not image.isNull():
            pixmap = QPixmap.fromImage(image).scaled(screen.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            screen.setPixmap(pixmap)

    def stop_camera(self, camera_id):
        worker = self.camera_workers.pop(camera_id, None)
        if worker:
            worker.stop()
            worker.wait(4500)
        screen = self.camera_screens.get(camera_id)
        if screen:
            screen.setPixmap(QPixmap())
            screen.setText("Видео остановлено")
        status = self.camera_status_labels.get(camera_id)
        if status:
            status.setText("● Видео остановлено")

    def add_school(self):
        name, ok = QInputDialog.getText(self, "Добавить школу", "Название школы:")
        name = name.strip()
        if not ok or not name:
            return
        con = db_connect()
        try:
            con.execute("INSERT INTO schools(name) VALUES (?)", (name,))
            con.commit()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Школа уже существует", "Школа с таким названием уже есть.")
        finally:
            con.close()
        self.refresh_schools()

    def add_camera(self):
        if self.current_school_id is None:
            return
        dialog = CameraDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values["name"]:
            QMessageBox.warning(self, "Не указано название", "Введите название камеры.")
            return
        con = db_connect()
        con.execute(
            "INSERT INTO cameras(school_id, name, location, rtsp_url) VALUES (?, ?, ?, ?)",
            (self.current_school_id, values["name"], values["location"], values["rtsp_url"])
        )
        con.commit()
        con.close()
        self.render_cameras()

    def edit_camera(self, camera_id, name, location, rtsp_url):
        dialog = CameraDialog(self, {"name": name, "location": location, "rtsp_url": rtsp_url})
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values["name"]:
            QMessageBox.warning(self, "Не указано название", "Введите название камеры.")
            return
        con = db_connect()
        con.execute(
            "UPDATE cameras SET name=?, location=?, rtsp_url=? WHERE id=?",
            (values["name"], values["location"], values["rtsp_url"], camera_id)
        )
        con.commit()
        con.close()
        self.render_cameras()

    def delete_camera(self, camera_id, name):
        answer = QMessageBox.question(
            self, "Удалить камеру?", f"Удалить «{name}» из списка?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        self.stop_camera(camera_id)
        con = db_connect()
        con.execute("DELETE FROM cameras WHERE id=?", (camera_id,))
        con.commit()
        con.close()
        self.render_cameras()

    def closeEvent(self, event):
        self.stop_all_workers()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SchoolVision()
    window.show()
    sys.exit(app.exec())
