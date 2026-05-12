'''
资源导出插件的入口类
'''
import qrenderdoc as qrd
from PySide2 import QtWidgets
from PySide2 import QtCore

from .csv_to_model.util import *
from .csv_to_model.exprorter import *
from .csv_to_model.exporter_dialog import ModelExportDialog

def log(message):
    with open(r"C:\Users\admin\Desktop\Log.txt", "a", encoding="utf-8") as f:
        print(message,file=f)


def _process_ui_events():
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents()


# 注册入口
def register(version_, pyrenderdoc_):
    emgr = pyrenderdoc_.Extensions()

    emgr.MessageDialog("插件注册成功","Info")

    if pyrenderdoc_.HasMeshPreview():
        emgr.RegisterPanelMenu(qrd.PanelMenu.MeshPreview, ["导出为模型"], ExportFbx)

# 异常捕获
def error_log(func_):
    def wrapper(pyrenderdoc, data):
        emgr = pyrenderdoc.Extensions()
        try:
            func_(pyrenderdoc, data)
        except:
            import traceback
            exc = traceback.format_exc()
            emgr.ErrorDialog(exc, "Error!!!")

    return wrapper


@error_log
def ExportFbx(pyrenderdoc_, data_):
    emgr = pyrenderdoc_.Extensions()


    #获取表格数据
    main_window = pyrenderdoc_.GetMainWindow().Widget()
    table = main_window.findChild(QtWidgets.QTableView, 'inTable')
    model = table.model()
    row_count = model.rowCount()
    column_count = model.columnCount()
    if row_count <= 1 and column_count <= 2:
        emgr.ErrorDialog("没有用于导出的模型数据", "错误")
        return
    
    #获取表头
    headers = [model.headerData(idx, QtCore.Qt.Horizontal) for idx in range(0,column_count)][2:]
    size_map = get_size_per_data(headers)
    dialog = ModelExportDialog(emgr, list(size_map.keys()))
    if not dialog.mqt.ShowWidgetAsDialog(dialog.init_ui()):
        return

    data_map = dialog.get_data_map(size_map)
    export_cfg = dialog.get_export_config()

    save_path = emgr.SaveFileName("选择模型导出的位置", '', '*.obj')
    if not save_path:
        emgr.ErrorDialog("选择的路径无效", 'Error!!!')
        return

    main_widget = pyrenderdoc_.GetMainWindow().Widget()
    progress = QtWidgets.QProgressDialog("正在读取表格数据…", "取消", 0, 100, main_widget)
    progress.setWindowTitle("导出模型")
    progress.setWindowModality(QtCore.Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()
    _process_ui_events()

    def _check_export_cancelled():
        _process_ui_events()
        if progress.wasCanceled():
            raise InterruptedError()

    try:
        def on_read_rows(cur: int, total: int) -> None:
            _check_export_cancelled()
            progress.setValue(int(85 * cur / max(total, 1)))
            progress.setLabelText(f"读取网格：{cur} / {total} 行")

        verts, idx = get_data_from_model(
            model, size_map, data_map, on_progress=on_read_rows
        )
    except InterruptedError:
        emgr.MessageDialog("已取消导出", "Info")
        return

    progress.setLabelText("正在写入 OBJ 文件…")
    progress.setValue(86)
    _process_ui_events()

    try:
        def on_write_obj(cur: int, total: int) -> None:
            _check_export_cancelled()
            progress.setValue(85 + int(15 * cur / max(total, 1)))
            progress.setLabelText(f"写入 OBJ：{cur} / {total}")

        paths = write_vertices_to_obj_per_uv(
            verts, idx, save_path, config=export_cfg, on_progress=on_write_obj
        )
    except InterruptedError:
        emgr.MessageDialog("已取消导出", "Info")
        return

    progress.setValue(100)
    progress.setLabelText("完成")
    _process_ui_events()

    emgr.MessageDialog("导出成功","Info")

