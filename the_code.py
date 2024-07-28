import sys
import subprocess
import json
import os
import psutil
import logging
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QFileDialog, QComboBox, QLabel, QMessageBox, QLineEdit, 
                             QGroupBox, QDialog, QTreeView, QCheckBox)
from PyQt6.QtGui import QColor, QStandardItemModel, QStandardItem
from PyQt6.QtCore import Qt, QTimer

# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Set up logging
current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f'logs/rclone_delta_gui_{current_time}.log'

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,  # Changed to INFO to capture more detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add a stream handler to also print logs to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # Changed to INFO
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logging.getLogger('').addHandler(console_handler)

class RemoteBrowserDialog(QDialog):
    def __init__(self, parent, config_file, remote):
        super().__init__(parent)
        self.setWindowTitle(f"Browse {remote}")
        self.setGeometry(200, 200, 400, 300)
        
        layout = QVBoxLayout()
        self.tree_view = QTreeView()
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)
        layout.addWidget(self.tree_view)
        
        self.select_button = QPushButton("Select")
        self.select_button.clicked.connect(self.accept)
        layout.addWidget(self.select_button)
        
        self.setLayout(layout)
        
        self.config_file = config_file
        self.remote = remote
        self.selected_path = ""
        
        self.populate_tree()
        
    def populate_tree(self, path=""):
        self.model.clear()
        self.model.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        
        cmd = ["rclone", "lsjson", "--config", self.config_file, f"{self.remote}:{path}"]
        try:
            output = subprocess.check_output(cmd, universal_newlines=True)
            items = json.loads(output)
        except subprocess.CalledProcessError as e:
            logging.error(f"Error executing rclone command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to list remote directory: {e}")
            return
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing rclone output: {e}")
            QMessageBox.critical(self, "Error", f"Failed to parse rclone output: {e}")
            return
        
        for item in items:
            name = QStandardItem(item['Name'])
            type_item = QStandardItem("Folder" if item['IsDir'] else "File")
            size = QStandardItem(format_size(item['Size']) if 'Size' in item else "")
            
            row = [name, type_item, size]
            self.model.appendRow(row)
            
            if item['IsDir']:
                name.setData(f"{path}{item['Name']}/", Qt.ItemDataRole.UserRole)
            else:
                name.setData(f"{path}{item['Name']}", Qt.ItemDataRole.UserRole)
        
        self.tree_view.clicked.connect(self.item_clicked)
        
    def item_clicked(self, index):
        item = self.model.itemFromIndex(index)
        path = item.data(Qt.ItemDataRole.UserRole)
        if path.endswith('/'):
            self.populate_tree(path)
        self.selected_path = path

def run_rclone_command(command):
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logging.error(f"rclone command failed: {stderr}")
            raise Exception(f"rclone command failed: {stderr}")
        logging.info(f"rclone command output: {stdout}")
        return stdout
    except Exception as e:
        logging.error(f"Error in run_rclone_command: {str(e)}", exc_info=True)
        raise

def get_rclone_configs(config_file):
    try:
        config_list_command = ["rclone", "config", "dump", "--config", config_file]
        config_dump = run_rclone_command(config_list_command)
        return json.loads(config_dump).keys()
    except Exception as e:
        logging.error(f"Error in get_rclone_configs: {str(e)}", exc_info=True)
        raise

def validate_rclone_config(config_file, config_name):
    try:
        if config_name == "local":
            return True
        config_list_command = ["rclone", "config", "show", config_name, "--config", config_file]
        output = run_rclone_command(config_list_command)
        return "type =" in output
    except Exception:
        return False
    
def run_rclone_lsjson(path, config_file=None, config_name=None, use_fast_list=True):
    base_cmd = ["rclone", "lsjson", "--recursive"]
    if use_fast_list:
        base_cmd.append("--fast-list")
    exclusion = ['--exclude', '/System Volume Information/**']
    
    if config_file and config_name:
        cmd = base_cmd + ["--config", config_file] + exclusion + [f"{config_name}:{path}"]
    else:
        cmd = base_cmd + exclusion + [path]
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logging.error(f"rclone lsjson command failed: {stderr}")
            raise Exception(f"rclone lsjson command failed: {stderr}")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON from rclone lsjson: {e}")
            raise
    except UnicodeDecodeError as e:
        logging.error(f"UnicodeDecodeError in run_rclone_lsjson: {str(e)}")
        raise
    except Exception as e:
        logging.error(f"Error in run_rclone_lsjson: {str(e)}", exc_info=True)
        raise


def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0

def ensure_trailing_slash(path):
    return path if path.endswith('/') or path.endswith(':\\') else path + '/'

class DeltaTreeWidget(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["Name", "Status", "Size"])
        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 100)

    def add_item(self, path, status, size):
        parts = path.split('/')
        parent = self.invisibleRootItem()
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                item = QTreeWidgetItem(parent)
                item.setText(0, part)
                item.setText(1, status)
                item.setText(2, format_size(size))
                if status == "New":
                    item.setBackground(0, QColor(200, 255, 200))
                elif status == "Deleted":
                    item.setBackground(0, QColor(255, 200, 200))
                elif status == "Modified":
                    item.setBackground(0, QColor(255, 255, 200))
            else:
                found = False
                for j in range(parent.childCount()):
                    if parent.child(j).text(0) == part:
                        parent = parent.child(j)
                        found = True
                        break
                if not found:
                    new_parent = QTreeWidgetItem(parent)
                    new_parent.setText(0, part)
                    parent = new_parent

    def calculate_directory_sizes(self):
        def recurse(item):
            total_size = 0
            for i in range(item.childCount()):
                child = item.child(i)
                if child.childCount() > 0:
                    child_size = recurse(child)
                    total_size += child_size
                    child.setText(2, format_size(child_size))
                else:
                    size_text = child.text(2)
                    if size_text:
                        total_size += float(size_text.split()[0])
            return total_size

        recurse(self.invisibleRootItem())

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rclone Delta GUI")
        self.setGeometry(100, 100, 900, 700)

        self.config_file = None
        self.source_config = None
        self.dest_config = None
        self.source_path = None
        self.dest_path = None

        layout = QVBoxLayout()
        
        # Config selection
        config_layout = QHBoxLayout()
        self.config_button = QPushButton("Select rclone config")
        self.config_button.clicked.connect(self.select_config)
        config_layout.addWidget(self.config_button)
        layout.addLayout(config_layout)

        # Source selection
        source_group = QGroupBox("Source")
        source_layout = QVBoxLayout()
        source_group.setLayout(source_layout)

        source_path_layout = QHBoxLayout()
        self.source_config_combo = QComboBox()
        self.source_path_input = QLineEdit()
        self.source_browse_button = QPushButton("Browse")
        self.source_browse_button.clicked.connect(self.browse_source)
        source_path_layout.addWidget(self.source_config_combo)
        source_path_layout.addWidget(self.source_path_input)
        source_path_layout.addWidget(self.source_browse_button)
        source_layout.addLayout(source_path_layout)

        layout.addWidget(source_group)

        # Destination selection
        dest_group = QGroupBox("Destination")
        dest_layout = QVBoxLayout()
        dest_group.setLayout(dest_layout)

        dest_path_layout = QHBoxLayout()
        self.dest_config_combo = QComboBox()
        self.dest_path_input = QLineEdit()
        self.dest_browse_button = QPushButton("Browse")
        self.dest_browse_button.clicked.connect(self.browse_dest)
        dest_path_layout.addWidget(self.dest_config_combo)
        dest_path_layout.addWidget(self.dest_path_input)
        dest_path_layout.addWidget(self.dest_browse_button)
        dest_layout.addLayout(dest_path_layout)

        layout.addWidget(dest_group)
        
        # Fast-list checkbox
        self.fast_list_checkbox = QCheckBox("Use --fast-list")
        self.fast_list_checkbox.setChecked(True)
        layout.addWidget(self.fast_list_checkbox)

        # Tree widget
        self.tree = DeltaTreeWidget()
        layout.addWidget(self.tree)

        # Buttons
        button_layout = QHBoxLayout()
        compare_button = QPushButton("Compare Directories")
        compare_button.clicked.connect(self.compare_directories)
        button_layout.addWidget(compare_button)

        sync_button = QPushButton("Run Full Sync")
        sync_button.clicked.connect(self.run_full_sync)
        button_layout.addWidget(sync_button)
        
        layout.addLayout(button_layout)

        # Memory usage
        self.memory_label = QLabel()
        layout.addWidget(self.memory_label)

        # Add status labels for config validation
        self.source_status_label = QLabel()
        self.dest_status_label = QLabel()
        layout.addWidget(self.source_status_label)
        layout.addWidget(self.dest_status_label)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        # Update memory usage every second
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_memory_usage)
        self.timer.start(1000)

        self.load_session_settings()

    def select_config(self):
        self.config_file, _ = QFileDialog.getOpenFileName(self, "Select rclone config file")
        if self.config_file:
            self.update_config_combos()
            self.save_session_settings()
            self.config_button.setText("Change rclone config")
    
    def compare_directories(self):
        if not self.config_file:
            QMessageBox.warning(self, "Error", "Please select an rclone config file first.")
            return

        self.source_config = self.source_config_combo.currentText()
        self.dest_config = self.dest_config_combo.currentText()

        self.source_path = ensure_trailing_slash(self.source_path_input.text())
        self.dest_path = ensure_trailing_slash(self.dest_path_input.text())

        if not self.source_path or not self.dest_path:
            QMessageBox.warning(self, "Error", "Please select both source and destination paths.")
            return

        use_fast_list = self.fast_list_checkbox.isChecked()

        self.tree.clear()
        try:
            source_files = {}
            dest_files = {}
            
            logging.info("Scanning source directory...")
            if self.source_config == "local":
                source_items = run_rclone_lsjson(self.source_path, use_fast_list=use_fast_list)
            else:
                source_items = run_rclone_lsjson(self.source_path, self.config_file, self.source_config, use_fast_list)
            for item in source_items:
                source_files[item['Path']] = item
            
            logging.info("Scanning destination directory...")
            if self.dest_config == "local":
                dest_items = run_rclone_lsjson(self.dest_path, use_fast_list=use_fast_list)
            else:
                dest_items = run_rclone_lsjson(self.dest_path, self.config_file, self.dest_config, use_fast_list)
            for item in dest_items:
                dest_files[item['Path']] = item

            for path, info in source_files.items():
                if path not in dest_files:
                    self.tree.add_item(path, "New", info['Size'])
                elif info['ModTime'] != dest_files[path]['ModTime']:
                    self.tree.add_item(path, "Modified", info['Size'])

            for path, info in dest_files.items():
                if path not in source_files:
                    self.tree.add_item(path, "Deleted", info['Size'])

            self.tree.calculate_directory_sizes()
            self.save_session_settings()
        except Exception as e:
            logging.error(f"Error in compare_directories: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"An error occurred while comparing directories: {str(e)}\n\nCheck the log file for details.")
            
    def update_config_combos(self):
        try:
            configs = list(get_rclone_configs(self.config_file))
            self.source_config_combo.clear()
            self.dest_config_combo.clear()
            self.source_config_combo.addItems(["local"] + configs)
            self.dest_config_combo.addItems(["local"] + configs)
            
            # Adjust dropdown length
            max_length = max(len(config) for config in configs + ["local"])
            max_visible_items = min(10, len(configs) + 1)
            self.source_config_combo.setStyleSheet(f"combobox-popup: 0;")
            self.dest_config_combo.setStyleSheet(f"combobox-popup: 0;")
            self.source_config_combo.view().setFixedWidth(max_length * 10)
            self.dest_config_combo.view().setFixedWidth(max_length * 10)
            self.source_config_combo.setMaxVisibleItems(max_visible_items)
            self.dest_config_combo.setMaxVisibleItems(max_visible_items)

            # Connect signals for config validation
            self.source_config_combo.currentTextChanged.connect(self.validate_source_config)
            self.dest_config_combo.currentTextChanged.connect(self.validate_dest_config)

            # Initial validation
            self.validate_source_config()
            self.validate_dest_config()

            # Update config button text
            self.config_button.setText("Change rclone config")
        except Exception as e:
            logging.error(f"Error in update_config_combos: {str(e)}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to update config combos. Check the log file for details.")

    def browse_source(self):
        self.browse_path(self.source_path_input, self.source_config_combo)

    def browse_dest(self):
        self.browse_path(self.dest_path_input, self.dest_config_combo)

    def browse_path(self, path_input, config_combo):
        if config_combo.currentText() == "local":
            path = QFileDialog.getExistingDirectory(self, "Select Directory")
            if path:
                path_input.setText(ensure_trailing_slash(path))
        else:
            remote = config_combo.currentText()
            dialog = RemoteBrowserDialog(self, self.config_file, remote)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                path_input.setText(ensure_trailing_slash(dialog.selected_path))

    def validate_source_config(self):
        self.validate_config(self.source_config_combo, self.source_status_label)

    def validate_dest_config(self):
        self.validate_config(self.dest_config_combo, self.dest_status_label)

    def validate_config(self, combo, status_label):
        config_name = combo.currentText()
        if self.config_file and config_name:
            is_valid = validate_rclone_config(self.config_file, config_name)
            status_label.setText(f"Config '{config_name}': {'Valid' if is_valid else 'Invalid'}")
            status_label.setStyleSheet("color: green;" if is_valid else "color: red;")
        else:
            status_label.setText("")

    def run_full_sync(self):
        if not all([self.config_file, self.source_config, self.dest_config, self.source_path, self.dest_path]):
            QMessageBox.warning(self, "Error", "Please compare directories before running a full sync.")
            return

        reply = QMessageBox.question(self, 'Confirm Sync', 
                                     'Are you sure you want to run a full sync? This will modify your destination directory.',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            try:
                source_path = self.source_path if self.source_config == "local" else f"{self.source_config}:{self.source_path}"
                dest_path = self.dest_path if self.dest_config == "local" else f"{self.dest_config}:{self.dest_path}"
                sync_command = ["rclone", "sync", "--config", self.config_file, source_path, dest_path]
                output = run_rclone_command(sync_command)
                QMessageBox.information(self, "Sync Complete", "The sync operation has completed successfully.")
                self.save_session_settings()
            except Exception as e:
                logging.error(f"Error in run_full_sync: {str(e)}", exc_info=True)
                QMessageBox.critical(self, "Error", f"An error occurred during sync. Check the log file for details.")

    def save_session_settings(self):
        settings = {
            "config_file": self.config_file,
            "source_config": self.source_config,
            "dest_config": self.dest_config,
            "source_path": self.source_path,
            "dest_path": self.dest_path,
            "use_fast_list": self.fast_list_checkbox.isChecked()
        }
        try:
            with open("session_settings.json", "w") as f:
                json.dump(settings, f)
        except Exception as e:
            logging.error(f"Error saving session settings: {str(e)}", exc_info=True)

    def load_session_settings(self):
        if os.path.exists("session_settings.json"):
            try:
                with open("session_settings.json", "r") as f:
                    settings = json.load(f)
                
                self.config_file = settings.get("config_file")
                if self.config_file:
                    self.update_config_combos()
                    self.config_button.setText("Change rclone config")
                
                self.source_config = settings.get("source_config")
                self.dest_config = settings.get("dest_config")
                self.source_path = settings.get("source_path")
                self.dest_path = settings.get("dest_path")
                
                self.source_config_combo.setCurrentText(self.source_config or "local")
                self.dest_config_combo.setCurrentText(self.dest_config or "local")
                
                self.source_path_input.setText(self.source_path or "")
                self.dest_path_input.setText(self.dest_path or "")
            except json.JSONDecodeError:
                logging.error("Invalid JSON in session_settings.json", exc_info=True)
            except Exception as e:
                logging.error(f"Error loading session settings: {str(e)}", exc_info=True)

    def update_memory_usage(self):
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        self.memory_label.setText(f"Memory Usage: {format_size(memory_info.rss)}")

if __name__ == "__main__":
    logging.info("Starting Rclone Delta GUI application")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())