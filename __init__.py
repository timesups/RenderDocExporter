'''
资源导出插件的入口类
'''
import qrenderdoc as qrd
from PySide2 import QtWidgets
from PySide2 import QtCore

from .csv_to_model.mesh_from_eid import get_data_from_eid, probe_mesh_headers
from .csv_to_model.exporter_dialog import ModelExportDialog
from .csv_to_model.fbx_exporter import write_vertices_to_fbx
from .csv_to_model.obj_exporter import write_vertices_to_obj_per_uv

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
    emgr.RegisterPanelMenu(qrd.PanelMenu.EventBrowser, ["导出为模型"], ExportFbx)
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

    eid = pyrenderdoc_.CurEvent()
    action = pyrenderdoc_.CurAction()
    if action is None:
        emgr.ErrorDialog(f"EID {eid} 不是 Draw Call，请先选中一条绘制事件", "错误")
        return

    size_map, probe_err = probe_mesh_headers(pyrenderdoc_)
    if probe_err:
        emgr.ErrorDialog(probe_err, "错误")
        return

    dialog = ModelExportDialog(emgr, list(size_map.keys()))
    if not dialog.mqt.ShowWidgetAsDialog(dialog.init_ui()):
        return

    data_map = dialog.get_data_map(size_map)
    decode_mode_map = dialog.get_decode_mode_map(size_map)
    export_cfg = dialog.get_export_config()

    save_path = emgr.SaveFileName(
        "选择模型导出的位置", "", "FBX (*.fbx);;OBJ (*.obj)"
    )
    if not save_path:
        emgr.ErrorDialog("选择的路径无效", 'Error!!!')
        return

    main_widget = pyrenderdoc_.GetMainWindow().Widget()
    progress = QtWidgets.QProgressDialog(
        f"正在读取 EID {eid} 网格数据…", "取消", 0, 100, main_widget
    )
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
            progress.setLabelText(f"读取网格：{cur} / {total} 索引")

        verts, idx = get_data_from_eid(
            pyrenderdoc_,
            size_map,
            data_map,
            on_progress=on_read_rows,
            decode_mode_map=decode_mode_map,
        )
    except InterruptedError:
        emgr.MessageDialog("已取消导出", "Info")
        return

    is_fbx = save_path.lower().endswith(".fbx")
    progress.setLabelText(
        "正在写入 FBX 文件…" if is_fbx else "正在写入 OBJ 文件…"
    )
    progress.setValue(86)
    _process_ui_events()

    try:
        def on_write_file(cur: int, total: int) -> None:
            _check_export_cancelled()
            progress.setValue(85 + int(15 * cur / max(total, 1)))
            label = "FBX" if is_fbx else "OBJ"
            progress.setLabelText(f"写入 {label}：{cur} / {total}")

        if is_fbx:
            write_vertices_to_fbx(
                verts, idx, save_path, config=export_cfg, on_progress=on_write_file
            )
            written_msg = save_path
        else:
            paths = write_vertices_to_obj_per_uv(
                verts, idx, save_path, config=export_cfg, on_progress=on_write_file
            )
            written_msg = "\n".join(paths)
    except InterruptedError:
        emgr.MessageDialog("已取消导出", "Info")
        return

    progress.setValue(100)
    progress.setLabelText("完成")
    _process_ui_events()

    emgr.MessageDialog(f"导出成功\n{written_msg}", "Info")

