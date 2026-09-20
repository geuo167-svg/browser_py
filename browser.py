import json
import os
import sys
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from PyQt6.QtCore import QCoreApplication, Qt, QUrl
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QProgressBar,
    QPushButton, QTabWidget, QToolBar, QVBoxLayout, QWidget, QHBoxLayout, QLabel,
    QTextBrowser, QMessageBox, QGroupBox, QDialog, QFormLayout, QScrollArea
)
from PyQt6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineScript,
    QWebEngineUrlRequestInterceptor, QWebEngineDownloadRequest
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

# Constante de version actuelle du navigateur
CURRENT_BROWSER_VERSION = "1.0.0"

EXT_CONFIG_FILE = "extensions.json"
SETTINGS_FILE = "settings.json"
STORE_DATA_FILE = "store_installed.json"


class CookieBlockerInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, disabled_domains_set):
        super().__init__()
        self.disabled_domains = disabled_domains_set

    def interceptRequest(self, info):
        url = info.requestUrl().host()
        for domain in self.disabled_domains:
            if domain in url:
                info.setHttpHeader(b"Cookie", b"")
                break


class DownloadItemWidget(QWidget):
    def __init__(self, download_item: QWebEngineDownloadRequest):
        super().__init__()
        self.download_item = download_item

        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        filename = os.path.basename(download_item.downloadDirectory() + "/" + download_item.downloadFileName())
        self.label_name = QLabel(filename or "Fichier")
        self.label_status = QLabel("En cours...")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)

        layout.addWidget(self.label_name)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.label_status)
        self.setLayout(layout)

        self.download_item.receivedBytesChanged.connect(self.update_progress)
        self.download_item.isFinishedChanged.connect(self.on_finished)

    def update_progress(self):
        total = self.download_item.totalBytes()
        received = self.download_item.receivedBytes()
        if total > 0:
            percent = int((received / total) * 100)
            self.progress_bar.setValue(percent)
            self.label_status.setText(f"{received // 1024} KB / {total // 1024} KB")
        else:
            self.label_status.setText(f"{received // 1024} KB")

    def on_finished(self):
        state = self.download_item.state()
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            self.progress_bar.setValue(100)
            self.label_status.setText("Terminé ✔")
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            self.label_status.setText("Annulé ❌")
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            self.label_status.setText("Interrompu ⚠️")


class SelectExtensionsDialog(QDialog):
    def __init__(self, parent=None, js_files_info=None):
        super().__init__(parent)
        self.setWindowTitle("Sélectionner les extensions à installer")
        self.resize(450, 400)
        self.js_files_info = js_files_info or []
        self.selected_files = []

        layout = QVBoxLayout(self)

        lbl = QLabel("Cochez les extensions que vous souhaitez importer :")
        lbl.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        
        self.checkboxes = []
        for file_info in self.js_files_info:
            cb = QCheckBox(file_info["name"])
            cb.setChecked(True)
            self.scroll_layout.addWidget(cb)
            self.checkboxes.append((cb, file_info))

        self.scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        btn_all = QPushButton("Tout cocher")
        btn_all.clicked.connect(lambda: self.set_all_checked(True))
        btn_none = QPushButton("Tout décocher")
        btn_none.clicked.connect(lambda: self.set_all_checked(False))
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        layout.addLayout(btn_layout)

        self.btn_install = QPushButton("📥 Installer la sélection")
        self.btn_install.setStyleSheet("background-color: #2ea44f; color: white; font-weight: bold; padding: 8px;")
        self.btn_install.clicked.connect(self.accept_selection)
        layout.addWidget(self.btn_install)

    def set_all_checked(self, checked):
        for cb, _ in self.checkboxes:
            cb.setChecked(checked)

    def accept_selection(self):
        self.selected_files = [file_info for cb, file_info in self.checkboxes if cb.isChecked()]
        if not self.selected_files:
            QMessageBox.warning(self, "Attention", "Veuillez sélectionner au moins une extension.")
            return
        self.accept()


class PublishGitHubDialog(QDialog):
    def __init__(self, parent=None, default_token="", default_repo=""):
        super().__init__(parent)
        self.setWindowTitle("Publier une extension sur GitHub")
        self.resize(500, 360)

        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.input_token = QLineEdit()
        self.input_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_token.setText(default_token)
        self.input_token.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxx")

        btn_help_token = QPushButton("?")
        btn_help_token.setFixedWidth(30)
        btn_help_token.setStyleSheet("font-weight: bold; background-color: #3b82f6; color: white; border-radius: 4px;")
        btn_help_token.setToolTip("Aide : Comment publier et obtenir un token ?")
        btn_help_token.clicked.connect(self.show_token_help)

        token_layout = QHBoxLayout()
        token_layout.addWidget(self.input_token)
        token_layout.addWidget(btn_help_token)

        self.input_repo = QLineEdit()
        self.input_repo.setText(default_repo)
        self.input_repo.setPlaceholderText("utilisateur/mon-repo-store")

        self.input_branch = QLineEdit()
        self.input_branch.setText("main")

        self.input_files = QLineEdit()
        self.input_files.setReadOnly(True)
        self.input_files.setPlaceholderText("Aucun fichier sélectionné")

        btn_browse = QPushButton("Choisir des fichiers .js...")
        btn_browse.clicked.connect(self.browse_files)

        form_layout.addRow("GitHub Access Token (PAT) :", token_layout)
        form_layout.addRow("Dépôt GitHub (User/Repo) :", self.input_repo)
        form_layout.addRow("Branche :", self.input_branch)
        form_layout.addRow("Fichiers à publier :", self.input_files)
        form_layout.addRow("", btn_browse)

        layout.addLayout(form_layout)

        self.selected_file_paths = []
        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)

        btn_publish = QPushButton("🚀 Envoyer vers GitHub")
        btn_publish.setStyleSheet("background-color: #2ea44f; color: white; font-weight: bold; padding: 8px;")
        btn_publish.clicked.connect(self.publish_to_github)
        layout.addWidget(btn_publish)

        self.setLayout(layout)

    def show_token_help(self):
        help_msg = (
            "<b>⚠️ Conseils importants pour la publication :</b><br>"
            "• Assurez-vous que votre dépôt GitHub est bien configuré en mode <b>Public</b> pour que le navigateur puisse y accéder sans erreur.<br>"
            "• Donnez un <b>nom clair et facile à comprendre</b> à vos fichiers d'extension (ex: <code>dark-mode.js</code> ou <code>adblocker.js</code>) afin de les identifier facilement lors de l'installation.<br><br>"
            "<b>Comment créer un Personal Access Token (PAT) sur GitHub :</b><br>"
            "1. Connectez-vous à votre compte sur <a href='https://github.com'>GitHub</a>.<br>"
            "2. Cliquez sur votre photo de profil en haut à droite, puis sur <b>Settings</b>.<br>"
            "3. Tout en bas du menu de gauche, cliquez sur <b>Developer settings</b>.<br>"
            "4. Allez dans <b>Personal access tokens</b> > <b>Tokens (classic)</b>.<br>"
            "5. Cliquez sur <b>Generate new token (classic)</b>.<br>"
            "6. Donnez un nom à votre token (ex: <i>Navigateur Extensions</i>).<br>"
            "7. Cochez impérativement la case <b>`repo`</b> (Full control of private repositories).<br>"
            "8. Faites défiler vers le bas et cliquez sur <b>Generate token</b>.<br>"
            "9. Copiez la chaîne de caractères affichée (commençant par <code>ghp_</code>) et collez-la ici."
        )
        QMessageBox.information(self, "Aide & Avertissements : Publication GitHub", help_msg)

    def browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Sélectionner les fichiers .js de l'extension", "", "Fichiers JavaScript (*.js)"
        )
        if files:
            self.selected_file_paths = files
            filenames = [os.path.basename(f) for f in files]
            self.input_files.setText(", ".join(filenames))

    def publish_to_github(self):
        token = self.input_token.text().strip()
        repo = self.input_repo.text().strip()
        branch = self.input_branch.text().strip() or "main"

        if not token or not repo:
            QMessageBox.warning(self, "Champ manquant", "Veuillez saisir votre token GitHub et le dépôt.")
            return

        if not self.selected_file_paths:
            QMessageBox.warning(self, "Fichiers manquants", "Veuillez sélectionner au moins un fichier .js.")
            return

        self.lbl_status.setText("Publication en cours...")
        QApplication.processEvents()

        success_count = 0
        for file_path in self.selected_file_paths:
            filename = os.path.basename(file_path)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content_str = f.read()

                content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
                github_path = f"extensions/{filename}"
                url = f"https://api.github.com/repos/{repo}/contents/{github_path}"

                sha = None
                req_check = urllib.request.Request(url)
                req_check.add_header("Authorization", f"token {token}")
                req_check.add_header("User-Agent", "Python-Qt-Browser")

                try:
                    with urllib.request.urlopen(req_check) as response:
                        if response.status == 200:
                            data = json.loads(response.read().decode("utf-8"))
                            sha = data.get("sha")
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise e

                payload = {
                    "message": f"Publication de {filename} depuis le navigateur",
                    "content": content_b64,
                    "branch": branch
                }
                if sha:
                    payload["sha"] = sha

                req_put = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="PUT")
                req_put.add_header("Authorization", f"token {token}")
                req_put.add_header("Content-Type", "application/json")
                req_put.add_header("User-Agent", "Python-Qt-Browser")

                with urllib.request.urlopen(req_put) as response:
                    if response.status in (200, 201):
                        success_count += 1

            except Exception as err:
                QMessageBox.critical(self, "Erreur", f"Erreur lors de la publication de {filename} :\n{str(err)}")
                self.lbl_status.setText("Échec de la publication.")
                return

        if success_count == len(self.selected_file_paths):
            self.lbl_status.setText("✔ Publication réussie !")
            QMessageBox.information(self, "Succès", f"{success_count} fichier(s) envoyé(s) sur GitHub !")
            self.accept()


class Browser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Navigateur Python - v{CURRENT_BROWSER_VERSION}")
        self.resize(1360, 850)

        self.history_data = []
        self.remote_extensions = self.load_remote_extensions()

        self.disabled_cookie_domains = set()
        self.profile = QWebEngineProfile.defaultProfile()
        self.interceptor = CookieBlockerInterceptor(self.disabled_cookie_domains)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(self.handle_download_request)

        self.history_recording_enabled = True
        self.bookmarks = set()
        self.extension_paths = self.load_saved_extension_paths()
        self.loaded_scripts = {}
        self.settings = self.load_settings()

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tabs)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.btn_back = QPushButton("←")
        self.btn_back.setFixedWidth(30)
        self.btn_back.clicked.connect(self.go_back)
        toolbar.addWidget(self.btn_back)

        self.btn_forward = QPushButton("→")
        self.btn_forward.setFixedWidth(30)
        self.btn_forward.clicked.connect(self.go_forward)
        toolbar.addWidget(self.btn_forward)

        btn_new_tab = QPushButton("+")
        btn_new_tab.setFixedWidth(30)
        btn_new_tab.clicked.connect(lambda: self.add_new_tab())
        toolbar.addWidget(btn_new_tab)

        btn_reload_page = QPushButton("↻")
        btn_reload_page.setFixedWidth(30)
        btn_reload_page.clicked.connect(self.reload_current_tab)
        toolbar.addWidget(btn_reload_page)

        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Entrez une URL ou recherche...")
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        toolbar.addWidget(self.url_bar)

        self.bookmark_btn = QPushButton("☆")
        self.bookmark_btn.setFixedWidth(35)
        self.bookmark_btn.clicked.connect(self.toggle_bookmark)
        toolbar.addWidget(self.bookmark_btn)

        self.cookie_button = QPushButton("Cookies : ON")
        self.cookie_button.clicked.connect(self.toggle_cookies_for_current_site)
        toolbar.addWidget(self.cookie_button)

        btn_store = QPushButton("🛒 Store")
        btn_store.clicked.connect(self.toggle_store_panel)
        toolbar.addWidget(btn_store)

        self.menu_btn = QPushButton("☰ Menu")
        toolbar.addWidget(self.menu_btn)
        self.setup_main_menu()

        self.setup_docks()
        self.restore_saved_extensions()
        self.restore_remote_extensions()

        self.setup_shortcuts()
        self.apply_theme()

        self.add_new_tab(QUrl("https://search.brave.com"), "Brave Search")

    def load_remote_extensions(self):
        if os.path.exists(STORE_DATA_FILE):
            try:
                with open(STORE_DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_remote_extensions(self):
        with open(STORE_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.remote_extensions, f, ensure_ascii=False, indent=2)

    def fetch_and_install_from_github(self):
        raw_input = self.input_external_repo.text().strip()
        if not raw_input:
            QMessageBox.warning(self, "Erreur", "Saisissez un dépôt sous la forme 'utilisateur/repo'.")
            return

        repo_input = raw_input
        if "github.com/" in repo_input:
            parts = repo_input.split("github.com/")[1].strip("/").split("/")
            if len(parts) >= 2:
                repo_input = f"{parts[0]}/{parts[1]}"
        else:
            parts = repo_input.split("/")
            if len(parts) >= 2:
                repo_input = f"{parts[0]}/{parts[1]}"

        url = f"https://api.github.com/repos/{repo_input}/contents/extensions"
        
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Python-Qt-Browser")
            
            token = self.settings.get("github_token", "").strip()
            if token:
                req.add_header("Authorization", f"token {token}")
            
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    files_list = json.loads(response.read().decode("utf-8"))
                    js_files = [f for f in files_list if f.get("name", "").endswith(".js")]

                    if not js_files:
                        QMessageBox.information(self, "Info", "Aucun fichier .js trouvé dans le dossier 'extensions' de ce dépôt.")
                        return

                    dialog = SelectExtensionsDialog(self, js_files)
                    if dialog.exec() != QDialog.DialogCode.Accepted:
                        return

                    installed_now = 0
                    for file_info in dialog.selected_files:
                        file_name = file_info["name"]
                        download_url = file_info["download_url"]

                        file_req = urllib.request.Request(download_url)
                        file_req.add_header("User-Agent", "Python-Qt-Browser")
                        if token:
                            file_req.add_header("Authorization", f"token {token}")

                        with urllib.request.urlopen(file_req) as f_resp:
                            js_code = f_resp.read().decode("utf-8")

                        ext_key = f"{repo_input}/{file_name}"
                        self.remote_extensions[ext_key] = {
                            "repo": repo_input,
                            "filename": file_name,
                            "code": js_code
                        }
                        self.inject_script_code(ext_key, js_code)
                        installed_now += 1

                    self.save_remote_extensions()
                    self.update_store_ui()
                    self.reload_current_tab()
                    QMessageBox.information(self, "Succès", f"{installed_now} extension(s) importée(s) et installée(s) depuis {repo_input} !")

        except urllib.error.HTTPError as e:
            if e.code == 404:
                QMessageBox.critical(self, "Erreur", f"Dépôt introuvable ou dossier 'extensions' manquant pour : '{repo_input}'.\nVérifiez que :\n1. Le dépôt est public (ou utilisez un token valide).\n2. Le dossier 'extensions/' existe bien à la racine.")
            else:
                QMessageBox.critical(self, "Erreur HTTP", f"Code erreur : {e.code}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'importer le dépôt :\n{str(e)}")

    def check_for_browser_updates(self):
        """Vérifie la version du navigateur sur le dépôt GitHub geuo167-svg/browser_py"""
        api_url = "https://api.github.com/repos/geuo167-svg/browser_py/contents/version.json"
        try:
            req = urllib.request.Request(api_url)
            req.add_header("User-Agent", "Python-Qt-Browser")
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    # Le contenu encodé en base64 dans l'API GitHub
                    content_b64 = data.get("content", "")
                    version_json_str = base64.b64decode(content_b64).decode("utf-8")
                    version_data = json.loads(version_json_str)

                    remote_version = version_data.get("version", "1.0.0")
                    download_url = version_data.get("download_url", "")

                    if remote_version != CURRENT_BROWSER_VERSION:
                        msg = (
                            f"Une nouvelle version du navigateur est disponible !\n\n"
                            f"• Version actuelle : {CURRENT_BROWSER_VERSION}\n"
                            f"• Nouvelle version : {remote_version}\n\n"
                            "Souhaitez-vous télécharger et mettre à jour le navigateur ?"
                        )
                        reply = QMessageBox.question(self, "Mise à jour disponible 🚀", msg,
                                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        if reply == QMessageBox.StandardButton.Yes:
                            self.apply_browser_update(download_url)
                    else:
                        QMessageBox.information(self, "À jour", f"Vous utilisez déjà la dernière version ({CURRENT_BROWSER_VERSION}).")
        except Exception as e:
            QMessageBox.critical(self, "Erreur de mise à jour", f"Impossible de vérifier les mises à jour :\n{str(e)}")

    def apply_browser_update(self, download_url):
        if not download_url:
            QMessageBox.warning(self, "Erreur", "URL de téléchargement de la mise à jour introuvable.")
            return
        try:
            req = urllib.request.Request(download_url)
            req.add_header("User-Agent", "Python-Qt-Browser")
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    new_code = response.read().decode("utf-8")

                    # Récupère le chemin du fichier script actuel en cours d'exécution
                    current_file_path = os.path.abspath(sys.argv[0])
                    with open(current_file_path, "w", encoding="utf-8") as f:
                        f.write(new_code)

                    QMessageBox.information(self, "Mise à jour réussie", "Le navigateur a été mis à jour avec succès !\nIl va maintenant redémarrer.")
                    self.restart_browser()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Échec lors de l'application de la mise à jour :\n{str(e)}")

    def restore_remote_extensions(self):
        for ext_key, ext_data in self.remote_extensions.items():
            self.inject_script_code(ext_key, ext_data["code"])

    def uninstall_remote_extension(self, ext_key):
        if ext_key in self.remote_extensions:
            del self.remote_extensions[ext_key]
            self.save_remote_extensions()

            script_collection = self.profile.scripts()
            for script in script_collection.find(ext_key):
                script_collection.remove(script)

            self.update_store_ui()
            self.reload_current_tab()

    def inject_script_code(self, script_id, js_code):
        script = QWebEngineScript()
        script.setName(script_id)
        script.setSourceCode(js_code)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        self.profile.scripts().insert(script)

    def go_back(self):
        web_view = self.current_web_view()
        if web_view:
            web_view.back()

    def go_forward(self):
        web_view = self.current_web_view()
        if web_view:
            web_view.forward()

    def open_publish_dialog(self):
        token = self.settings.get("github_token", "")
        repo = self.settings.get("github_repo", "")
        dialog = PublishGitHubDialog(self, default_token=token, default_repo=repo)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings["github_token"] = dialog.input_token.text().strip()
            self.settings["github_repo"] = dialog.input_repo.text().strip()
            self.save_settings()

    def handle_download_request(self, download: QWebEngineDownloadRequest):
        default_path = os.path.join(os.path.expanduser("~"), "Downloads", download.downloadFileName())
        file_path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le fichier", default_path)
        
        if file_path:
            download.setDownloadDirectory(os.path.dirname(file_path))
            download.setDownloadFileName(os.path.basename(file_path))
            download.accept()

            item_widget = DownloadItemWidget(download)
            list_item = QListWidgetItem(self.downloads_list)
            list_item.setSizeHint(item_widget.sizeHint())
            self.downloads_list.addItem(list_item)
            self.downloads_list.setItemWidget(list_item, item_widget)
            self.downloads_dock.show()

    def load_settings(self):
        defaults = {"use_system_theme": True, "dark_mode": False, "search_engine": "Brave", "github_token": "", "github_repo": ""}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    defaults.update(json.load(f))
            except Exception:
                pass
        return defaults

    def save_settings(self):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)

    def is_system_in_dark_mode(self):
        window_color = QApplication.palette().color(QPalette.ColorRole.Window)
        return window_color.value() < 128

    def apply_theme(self):
        use_system = self.settings.get("use_system_theme", True)
        is_dark = self.is_system_in_dark_mode() if use_system else self.settings.get("dark_mode", False)

        if is_dark:
            dark_stylesheet = """
                QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4; }
                QLineEdit { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; border-radius: 6px; padding: 6px; }
                QPushButton { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; border-radius: 6px; padding: 5px 10px; font-weight: bold; }
                QPushButton:hover { background-color: #45475a; }
                QTabBar::tab { background: #181825; color: #a6adc8; padding: 8px 14px; border-radius: 4px; margin-right: 2px; }
                QTabBar::tab:selected { background: #313244; color: #cdd6f4; font-weight: bold; }
                QDockWidget { titlebar-close-icon: url(); titlebar-normal-icon: url(); font-weight: bold; }
                QListWidget { background-color: #181825; color: #cdd6f4; border: 1px solid #45475a; border-radius: 6px; }
                QMenu { background-color: #1e1e2e; color: #cdd6f4; border: 1px solid #45475a; }
                QMenu::item:selected { background-color: #313244; }
                QProgressBar { border: 1px solid #45475a; border-radius: 4px; text-align: center; }
                QProgressBar::chunk { background-color: #89b4fa; }
                QComboBox { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; padding: 4px; }
                QGroupBox { border: 1px solid #45475a; border-radius: 6px; margin-top: 10px; padding-top: 10px; font-weight: bold; }
                QTextBrowser { background-color: #181825; color: #cdd6f4; border: 1px solid #45475a; border-radius: 6px; }
                QScrollArea { background-color: transparent; border: none; }
            """
            QApplication.instance().setStyleSheet(dark_stylesheet)
        else:
            QApplication.instance().setStyleSheet("")

    def toggle_system_theme_setting(self, state):
        use_system = (state == Qt.CheckState.Checked.value or state == True)
        self.settings["use_system_theme"] = use_system
        self.theme_switch_btn.setEnabled(not use_system)
        self.save_settings()
        self.apply_theme()

    def toggle_manual_theme(self):
        current_mode = self.settings.get("dark_mode", False)
        self.settings["dark_mode"] = not current_mode
        self.update_theme_switch_button_text()
        self.save_settings()
        self.apply_theme()

    def update_theme_switch_button_text(self):
        if self.settings.get("dark_mode", False):
            self.theme_switch_btn.setText("Passer en Mode Clair ☀️")
        else:
            self.theme_switch_btn.setText("Passer en Mode Sombre 🌙")

    def restart_browser(self):
        self.save_extension_paths()
        self.save_settings()
        QCoreApplication.quit()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def load_saved_extension_paths(self):
        if os.path.exists(EXT_CONFIG_FILE):
            try:
                with open(EXT_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_extension_paths(self):
        with open(EXT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.extension_paths, f, ensure_ascii=False, indent=2)

    def restore_saved_extensions(self):
        valid_paths = []
        for path in self.extension_paths:
            if os.path.exists(path):
                self.register_extension(path)
                valid_paths.append(path)
        self.extension_paths = valid_paths
        self.save_extension_paths()

    def register_extension(self, file_path):
        filename = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            js_code = f.read()

        script = QWebEngineScript()
        script.setName(filename)
        script.setSourceCode(js_code)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)

        self.profile.scripts().insert(script)
        self.loaded_scripts[filename] = (script, file_path)

        items = self.extensions_list.findItems(filename, Qt.MatchFlag.MatchExactly)
        if not items:
            self.extensions_list.addItem(filename)

    def load_extension_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Charger un fichier JS", "", "JavaScript (*.js)"
        )
        if file_path:
            if file_path not in self.extension_paths:
                self.extension_paths.append(file_path)
                self.save_extension_paths()

            self.register_extension(file_path)
            self.reload_current_tab()

    def remove_selected_extension(self):
        selected_item = self.extensions_list.currentItem()
        if not selected_item:
            return

        filename = selected_item.text()
        if filename in self.loaded_scripts:
            script, file_path = self.loaded_scripts[filename]
            self.profile.scripts().remove(script)

            if file_path in self.extension_paths:
                self.extension_paths.remove(file_path)
                self.save_extension_paths()

            del self.loaded_scripts[filename]

        self.extensions_list.takeItem(self.extensions_list.row(selected_item))
        self.reload_current_tab()

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(lambda: self.add_new_tab())
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.reload_current_tab)
        QShortcut(QKeySequence("F5"), self).activated.connect(self.reload_current_tab)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self).activated.connect(self.restart_browser)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self.toggle_history_panel)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self.toggle_bookmarks_panel)
        QShortcut(QKeySequence("Ctrl+J"), self).activated.connect(self.toggle_downloads_panel)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self.toggle_store_panel)

    def setup_main_menu(self):
        main_menu = QMenu(self)

        self.act_history_toggle = QAction("Enregistrer l'historique : ON", self)
        self.act_history_toggle.triggered.connect(self.toggle_history_recording)
        main_menu.addAction(self.act_history_toggle)

        act_show_history = QAction("Ouvrir l'historique (Ctrl+H)", self)
        act_show_history.triggered.connect(self.toggle_history_panel)
        main_menu.addAction(act_show_history)

        main_menu.addSeparator()

        act_show_bookmarks = QAction("Ouvrir les favoris (Ctrl+B)", self)
        act_show_bookmarks.triggered.connect(self.toggle_bookmarks_panel)
        main_menu.addAction(act_show_bookmarks)

        act_show_downloads = QAction("Ouvrir les téléchargements (Ctrl+J)", self)
        act_show_downloads.triggered.connect(self.toggle_downloads_panel)
        main_menu.addAction(act_show_downloads)

        main_menu.addSeparator()

        act_show_store = QAction("🛒 Store & Import GitHub (Ctrl+Shift+S)", self)
        act_show_store.triggered.connect(self.toggle_store_panel)
        main_menu.addAction(act_show_store)

        act_show_guide = QAction("📚 Guide : Créer son extension", self)
        act_show_guide.triggered.connect(self.toggle_guide_panel)
        main_menu.addAction(act_show_guide)

        act_show_extensions = QAction("⚙️ Gérer les scripts JS locaux", self)
        act_show_extensions.triggered.connect(self.toggle_extensions_panel)
        main_menu.addAction(act_show_extensions)

        act_show_theme = QAction("🎨 Apparence & Paramètres", self)
        act_show_theme.triggered.connect(self.toggle_theme_panel)
        main_menu.addAction(act_show_theme)

        main_menu.addSeparator()

        act_check_update = QAction("🔄 Vérifier les mises à jour du navigateur", self)
        act_check_update.triggered.connect(self.check_for_browser_updates)
        main_menu.addAction(act_check_update)

        act_restart = QAction("Redémarrer le navigateur (Ctrl+Shift+R)", self)
        act_restart.triggered.connect(self.restart_browser)
        main_menu.addAction(act_restart)

        self.menu_btn.setMenu(main_menu)

    def setup_docks(self):
        self.store_dock = QDockWidget("🛒 Store GitHub", self)
        store_widget = QWidget()
        self.store_layout = QVBoxLayout()

        lbl_store_title = QLabel("Obtenir & Importer des Extensions")
        lbl_store_title.setStyleSheet("font-size: 15px; font-weight: bold; margin-bottom: 5px;")
        self.store_layout.addWidget(lbl_store_title)

        btn_publish_store = QPushButton("📤 Publier une extension sur GitHub")
        btn_publish_store.setStyleSheet("background-color: #2ea44f; color: white; font-weight: bold; margin-bottom: 10px;")
        btn_publish_store.clicked.connect(self.open_publish_dialog)
        self.store_layout.addWidget(btn_publish_store)

        import_group = QGroupBox("Télécharger depuis un dépôt GitHub")
        import_layout = QVBoxLayout()
        
        self.input_external_repo = QLineEdit()
        self.input_external_repo.setPlaceholderText("ex: pseudo/mon-repo")
        import_layout.addWidget(self.input_external_repo)

        btn_fetch_repo = QPushButton("📥 Charger/Sélectionner du dépôt")
        btn_fetch_repo.clicked.connect(self.fetch_and_install_from_github)
        import_layout.addWidget(btn_fetch_repo)
        
        import_group.setLayout(import_layout)
        self.store_layout.addWidget(import_group)

        lbl_installed = QLabel("Extensions GitHub installées :")
        lbl_installed.setStyleSheet("font-weight: bold; margin-top: 10px;")
        self.store_layout.addWidget(lbl_installed)

        self.store_container = QVBoxLayout()
        self.store_layout.addLayout(self.store_container)
        self.store_layout.addStretch()

        store_widget.setLayout(self.store_layout)
        self.store_dock.setWidget(store_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.store_dock)
        self.store_dock.hide()
        self.update_store_ui()

        self.guide_dock = QDockWidget("📚 Guide Extensions", self)
        guide_widget = QWidget()
        guide_layout = QVBoxLayout()

        guide_browser = QTextBrowser()
        guide_browser.setHtml("""
            <h2>Comment partager et installer des extensions ?</h2>
            <p>1. Créez un dépôt GitHub <b>public</b> et ajoutez-y un dossier nommé <code>extensions/</code>.</p>
            <p>2. Mettez vos fichiers <code>.js</code> dedans avec des noms clairs et validez (commit).</p>
            <p>3. Pour les installer, entrez simplement le nom du dépôt au format <code>utilisateur/depot</code> dans le champ d'importation (ex: <code>geuo167-svg/kk</code>).</p>
        """)
        guide_layout.addWidget(guide_browser)
        guide_widget.setLayout(guide_layout)
        self.guide_dock.setWidget(guide_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.guide_dock)
        self.guide_dock.hide()

        self.history_dock = QDockWidget("Historique", self)
        history_widget = QWidget()
        history_layout = QVBoxLayout()

        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.open_url_from_list)

        btn_delete_selected = QPushButton("Supprimer la page sélectionnée")
        btn_delete_selected.clicked.connect(self.delete_selected_history_item)

        shortcut_del = QShortcut(QKeySequence("Delete"), self.history_list)
        shortcut_del.activated.connect(self.delete_selected_history_item)

        self.period_combo = QComboBox()
        self.period_combo.addItems([
            "Dernière heure",
            "Dernières 24 heures",
            "7 derniers jours",
            "Tout l'historique"
        ])

        btn_delete_period = QPushButton("Effacer la période")
        btn_delete_period.clicked.connect(self.delete_history_by_period)

        history_layout.addWidget(self.history_list)
        history_layout.addWidget(btn_delete_selected)
        history_layout.addWidget(QLabel("Effacer par période :"))
        history_layout.addWidget(self.period_combo)
        history_layout.addWidget(btn_delete_period)
        history_widget.setLayout(history_layout)

        self.history_dock.setWidget(history_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.history_dock)
        self.history_dock.hide()

        self.bookmarks_dock = QDockWidget("Favoris", self)
        self.bookmarks_list = QListWidget()
        self.bookmarks_list.itemDoubleClicked.connect(self.open_url_from_list)
        self.bookmarks_dock.setWidget(self.bookmarks_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.bookmarks_dock)
        self.bookmarks_dock.hide()

        self.downloads_dock = QDockWidget("Téléchargements", self)
        self.downloads_list = QListWidget()
        self.downloads_dock.setWidget(self.downloads_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.downloads_dock)
        self.downloads_dock.hide()

        self.extensions_dock = QDockWidget("Scripts JS Locaux", self)
        ext_widget = QWidget()
        ext_layout = QVBoxLayout()

        self.extensions_list = QListWidget()
        btn_load = QPushButton("Charger un fichier .js")
        btn_load.clicked.connect(self.load_extension_file)

        btn_remove = QPushButton("Retirer l'extension sélectionnée")
        btn_remove.clicked.connect(self.remove_selected_extension)

        ext_layout.addWidget(self.extensions_list)
        ext_layout.addWidget(btn_load)
        ext_layout.addWidget(btn_remove)
        ext_widget.setLayout(ext_layout)

        self.extensions_dock.setWidget(ext_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.extensions_dock)
        self.extensions_dock.hide()

        self.theme_dock = QDockWidget("Apparence", self)
        theme_widget = QWidget()
        theme_layout = QVBoxLayout()

        self.system_theme_checkbox = QCheckBox("Suivre les paramètres système")
        self.system_theme_checkbox.setChecked(self.settings.get("use_system_theme", True))
        self.system_theme_checkbox.stateChanged.connect(self.toggle_system_theme_setting)

        self.theme_switch_btn = QPushButton()
        self.update_theme_switch_button_text()
        self.theme_switch_btn.clicked.connect(self.toggle_manual_theme)
        self.theme_switch_btn.setEnabled(not self.settings.get("use_system_theme", True))

        theme_layout.addWidget(self.system_theme_checkbox)
        theme_layout.addWidget(self.theme_switch_btn)
        theme_layout.addStretch()
        theme_widget.setLayout(theme_layout)

        self.theme_dock.setWidget(theme_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.theme_dock)
        self.theme_dock.hide()

    def update_store_ui(self):
        while self.store_container.count():
            item = self.store_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.remote_extensions:
            lbl_empty = QLabel("<i>Aucune extension distante installée.</i>")
            self.store_container.addWidget(lbl_empty)
            return

        for ext_key, ext_data in self.remote_extensions.items():
            box = QGroupBox(ext_data["filename"])
            box_layout = QVBoxLayout()

            desc = QLabel(f"Source: <b>{ext_data['repo']}</b>")
            box_layout.addWidget(desc)

            btn_del = QPushButton("Désinstaller")
            btn_del.setStyleSheet("background-color: #f38ba8; color: #11111b;")
            btn_del.clicked.connect(lambda checked, key=ext_key: self.uninstall_remote_extension(key))

            box_layout.addWidget(btn_del)
            box.setLayout(box_layout)
            self.store_container.addWidget(box)

    def delete_selected_history_item(self):
        row = self.history_list.currentRow()
        if row >= 0:
            self.history_list.takeItem(row)
            if row < len(self.history_data):
                del self.history_data[row]

    def delete_history_by_period(self):
        selected_period = self.period_combo.currentText()
        now = datetime.now()

        if selected_period == "Tout l'historique":
            self.history_data.clear()
            self.history_list.clear()
            return

        if selected_period == "Dernière heure":
            cutoff = now - timedelta(hours=1)
        elif selected_period == "Dernières 24 heures":
            cutoff = now - timedelta(days=1)
        elif selected_period == "7 derniers jours":
            cutoff = now - timedelta(days=7)
        else:
            return

        self.history_data = [item for item in self.history_data if item[0] < cutoff]
        self.history_list.clear()
        for timestamp, url in self.history_data:
            self.history_list.addItem(url)

    def current_web_view(self):
        return self.tabs.currentWidget()

    def add_new_tab(self, qurl=None, label="Nouvel onglet"):
        if qurl is None:
            qurl = QUrl("https://search.brave.com")

        web_view = QWebEngineView()
        page = QWebEnginePage(self.profile, web_view)
        web_view.setPage(page)
        web_view.setUrl(qurl)

        index = self.tabs.addTab(web_view, label)
        self.tabs.setCurrentIndex(index)

        web_view.urlChanged.connect(lambda url: self.on_url_changed(url, web_view))
        web_view.titleChanged.connect(lambda title: self.on_title_changed(title, web_view))

    def close_tab(self, index):
        if self.tabs.count() > 1:
            self.tabs.removeTab(index)
        else:
            self.close()

    def reload_current_tab(self):
        web_view = self.current_web_view()
        if web_view:
            web_view.reload()

    def on_tab_changed(self, index):
        web_view = self.current_web_view()
        if web_view:
            self.url_bar.setText(web_view.url().toString())
            self.update_cookie_button_label()
            self.update_bookmark_button()

    def on_url_changed(self, url, web_view):
        url_str = url.toString()
        if web_view == self.current_web_view():
            self.url_bar.setText(url_str)
            self.update_cookie_button_label()
            self.update_bookmark_button()

        if self.history_recording_enabled and url_str and url_str != "about:blank":
            self.history_data.append((datetime.now(), url_str))
            self.history_list.addItem(url_str)

    def on_title_changed(self, title, web_view):
        index = self.tabs.indexOf(web_view)
        if index != -1:
            short_title = title[:15] + "..." if len(title) > 15 else title
            self.tabs.setTabText(index, short_title or "Nouvel onglet")

    def navigate_to_url(self):
        text = self.url_bar.text().strip()
        
        if text.startswith("http://") or text.startswith("https://"):
            url = text
        elif "." in text and " " not in text:
            url = f"https://{text}"
        else:
            url = f"https://search.brave.com/search?q={text}"

        web_view = self.current_web_view()
        if web_view:
            web_view.setUrl(QUrl(url))

    def toggle_history_recording(self):
        self.history_recording_enabled = not self.history_recording_enabled
        status = "ON" if self.history_recording_enabled else "OFF"
        self.act_history_toggle.setText(f"Enregistrer l'historique : {status}")

    def toggle_history_panel(self):
        self.history_dock.setVisible(not self.history_dock.isVisible())

    def toggle_bookmarks_panel(self):
        self.bookmarks_dock.setVisible(not self.bookmarks_dock.isVisible())

    def toggle_downloads_panel(self):
        self.downloads_dock.setVisible(not self.downloads_dock.isVisible())

    def toggle_extensions_panel(self):
        self.extensions_dock.setVisible(not self.extensions_dock.isVisible())

    def toggle_theme_panel(self):
        self.theme_dock.setVisible(not self.theme_dock.isVisible())

    def toggle_store_panel(self):
        self.store_dock.setVisible(not self.store_dock.isVisible())

    def toggle_guide_panel(self):
        self.guide_dock.setVisible(not self.guide_dock.isVisible())

    def toggle_bookmark(self):
        web_view = self.current_web_view()
        if not web_view:
            return

        url = web_view.url().toString()
        if not url or url == "about:blank":
            return

        if url in self.bookmarks:
            self.bookmarks.remove(url)
        else:
            self.bookmarks.add(url)

        self.bookmarks_list.clear()
        for b_url in self.bookmarks:
            self.bookmarks_list.addItem(b_url)

        self.update_bookmark_button()

    def update_bookmark_button(self):
        web_view = self.current_web_view()
        if not web_view:
            self.bookmark_btn.setText("☆")
            return

        url = web_view.url().toString()
        if url in self.bookmarks:
            self.bookmark_btn.setText("★")
        else:
            self.bookmark_btn.setText("☆")

    def toggle_cookies_for_current_site(self):
        web_view = self.current_web_view()
        if not web_view:
            return

        domain = web_view.url().host()
        if not domain:
            return

        if domain in self.disabled_cookie_domains:
            self.disabled_cookie_domains.remove(domain)
        else:
            self.disabled_cookie_domains.add(domain)

        self.update_cookie_button_label()
        web_view.reload()

    def update_cookie_button_label(self):
        web_view = self.current_web_view()
        if not web_view:
            self.cookie_button.setText("Cookies : N/A")
            return

        domain = web_view.url().host()
        if not domain:
            self.cookie_button.setText("Cookies : N/A")
            return

        is_disabled = domain in self.disabled_cookie_domains
        status = "OFF" if is_disabled else "ON"
        self.cookie_button.setText(f"Cookies ({domain}) : {status}")

    def open_url_from_list(self, item):
        url = item.text()
        web_view = self.current_web_view()
        if web_view:
            web_view.setUrl(QUrl(url))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Browser()
    window.show()
    sys.exit(app.exec())
