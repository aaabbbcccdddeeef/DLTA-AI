import os.path as osp
import shutil
import tempfile

import qtpy

import labelme.app
import labelme.config
import labelme.testing


here = osp.dirname(osp.abspath(__file__))
data_dir = osp.join(here, 'data')


def test_MainWindow_open(qtbot):
    win = labelme.app.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.close()


def test_MainWindow_open_json(qtbot):
    if qtpy.PYQT4:
        # Fails to load image from JSON on Anaconda + Python2.7 + PyQt4
        return

    filename = osp.join(data_dir, 'apc2016_obj3.json')
    labelme.testing.assert_labelfile_sanity(filename)
    win = labelme.app.MainWindow(filename=filename)
    qtbot.addWidget(win)
    win.show()
    win.close()


def test_MainWindow_annotate_jpg(qtbot):
    if qtpy.PYQT4:
        # Fails to load image from JSON on Anaconda + Python2.7 + PyQt4
        return

    tmp_dir = tempfile.mkdtemp()
    filename = osp.join(tmp_dir, 'apc2016_obj3.jpg')
    shutil.copy(osp.join(data_dir, 'apc2016_obj3.jpg'),
                filename)
    output = osp.join(tmp_dir, 'apc2016_obj3.json')

    config = labelme.config.get_default_config()
    win = labelme.app.MainWindow(
        config=config, filename=filename, output=output)
    qtbot.addWidget(win)
    win.show()

    def check_imageData():
        assert hasattr(win, 'imageData')
        assert win.imageData is not None

    qtbot.waitUntil(check_imageData)  # wait for loadFile

    label = 'shelf'
    points = [
        (26, 70),
        (176, 730),
        (986, 742),
        (1184, 102),
    ]
    shape = label, points, None, None
    shapes = [shape]
    win.loadLabels(shapes)
    win.saveFile()

    labelme.testing.assert_labelfile_sanity(output)
