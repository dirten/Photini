# -*- coding: utf-8 -*-
##  Photini - a simple photo metadata editor.
##  http://github.com/jim-easterbrook/Photini
##  Copyright (C) 2012-19  Jim Easterbrook  jim@jim-easterbrook.me.uk
##
##  This program is free software: you can redistribute it and/or
##  modify it under the terms of the GNU General Public License as
##  published by the Free Software Foundation, either version 3 of the
##  License, or (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
##  General Public License for more details.
##
##  You should have received a copy of the GNU General Public License
##  along with this program.  If not, see
##  <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

import six
from datetime import datetime
import imghdr
import logging
import mimetypes
import os
from six import BytesIO
from six.moves.urllib.parse import unquote
import webbrowser

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
try:
    import PIL.Image as PIL
except ImportError:
    PIL = None

from photini.metadata import Metadata, MultiString
from photini.pyqt import (
    Busy, catch_all, image_types, Qt, QtCore, QtGui, QtWidgets, qt_version_info,
    scale_font, set_symbol_font, video_types)

logger = logging.getLogger(__name__)
DRAG_MIMETYPE = 'application/x-photini-image'


class TableWidget(QtWidgets.QTableWidget):
    @catch_all
    def sizeHint(self):
        h_hdr = self.horizontalHeader()
        v_hdr = self.verticalHeader()
        return QtCore.QSize(h_hdr.length() + v_hdr.sizeHint().width() + 4,
                            v_hdr.length() + h_hdr.sizeHint().height() + 4)


class Image(QtWidgets.QFrame):
    def __init__(self, path, image_list, thumb_size=80, *arg, **kw):
        super(Image, self).__init__(*arg, **kw)
        self.path = path
        self.image_list = image_list
        self.name, ext = os.path.splitext(os.path.basename(self.path))
        self.selected = False
        self.thumb_size = thumb_size
        # read metadata
        self.metadata = Metadata(self.path)
        self.metadata.unsaved.connect(self.show_status)
        self.file_times = (os.path.getatime(self.path),
                           os.path.getmtime(self.path))
        # set file type
        self.file_type = self.metadata.get_mime_type()
        if not self.file_type:
            self.file_type = mimetypes.guess_type(self.path)[0]
        if not self.file_type:
            self.file_type = imghdr.what(self.path)
            if self.file_type:
                self.file_type = 'image/' + self.file_type
        # anything not recognised is assumed to be 'raw'
        if not self.file_type:
            self.file_type = 'image/raw'
        # sub widgets
        layout = QtWidgets.QGridLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(3, 3, 3, 3)
        self.setLayout(layout)
        self.setToolTip(self.path)
        # label to display image
        self.image = QtWidgets.QLabel()
        self.image.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        layout.addWidget(self.image, 0, 0, 1, 2)
        # label to display file name
        self.label = QtWidgets.QLabel()
        self.label.setAlignment(Qt.AlignRight)
        scale_font(self.label, 80)
        layout.addWidget(self.label, 1, 1)
        # label to display status
        self.status = QtWidgets.QLabel()
        self.status.setAlignment(Qt.AlignLeft)
        set_symbol_font(self.status)
        scale_font(self.status, 80)
        layout.addWidget(self.status, 1, 0)
        self.setFrameStyle(QtWidgets.QFrame.Panel | QtWidgets.QFrame.Plain)
        self.setObjectName("thumbnail")
        self.set_selected(False)
        self.show_status(False)
        self._set_thumb_size(self.thumb_size)

    @QtCore.pyqtSlot()
    @catch_all
    def reload_metadata(self):
        self.metadata = Metadata(self.path)
        self.metadata.unsaved.connect(self.show_status)
        self.show_status(False)
        self.load_thumbnail()
        self.image_list.emit_selection()

    @QtCore.pyqtSlot()
    @catch_all
    def save_metadata(self):
        self.image_list._save_files(images=[self])

    @QtCore.pyqtSlot()
    @catch_all
    def diff_metadata(self):
        dialog = QtWidgets.QDialog(parent=self)
        dialog.setWindowTitle(self.tr('Metadata differences'))
        dialog.setLayout(QtWidgets.QVBoxLayout())
        table = TableWidget()
        table.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                            QtWidgets.QSizePolicy.Expanding)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(
            [self.tr('new value'), self.tr('undo'), self.tr('old value')])
        labels = []
        row = 0
        undo = {}
        new_md = self.metadata
        old_md = Metadata(self.path)
        for key in ('title', 'description', 'keywords', 'rating',
                    'copyright', 'creator',
                    'date_taken', 'date_digitised', 'date_modified',
                    'orientation',
                    'lens_model', 'lens_make', 'lens_serial', 'lens_spec',
                    'focal_length', 'focal_length_35', 'aperture',
                    'latlong', 'location_taken', 'location_shown',
                    'thumbnail'):
            values = getattr(new_md, key), getattr(old_md, key)
            if values[0] == values[1]:
                continue
            table.setRowCount(row + 1)
            for n, value in enumerate(values):
                if not value:
                    value = ''
                elif isinstance(value, MultiString):
                    value = '\n'.join(value)
                else:
                    value = six.text_type(value)
                item = QtWidgets.QTableWidgetItem(value)
                table.setItem(row, n * 2, item)
            undo[key] = QtWidgets.QTableWidgetItem()
            undo[key].setFlags(undo[key].flags() | Qt.ItemIsUserCheckable)
            undo[key].setCheckState(False)
            table.setItem(row, 1, undo[key])
            labels.append(key)
            row += 1
        table.setVerticalHeaderLabels(labels)
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        dialog.layout().addWidget(table)
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        dialog.layout().addWidget(button_box)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        changed = False
        dirty = False
        for key, widget in undo.items():
            if widget.checkState() == Qt.Checked:
                setattr(new_md, key, getattr(old_md, key))
                changed = True
            else:
                dirty = True
        if not dirty:
            self.reload_metadata()
        elif changed:
            self.image_list.emit_selection()

    def get_video_frame(self):
        if not cv2:
            return
        video = cv2.VideoCapture(self.path)
        if not video.isOpened():
            return
        OK, cv_image = video.read()
        if not OK:
            return
        height, width, channel = cv_image.shape
        fmt = QtGui.QImage.Format_RGB888
        # need to pad to 4 pixel multiple
        new_width = width - (width % -4)
        if channel == 4:
            # assume BGRA
            fmt = QtGui.QImage.Format_ARGB32
            np_image = np.empty((height, new_width, channel), dtype=np.uint8)
            np_image[ : , :width, 0] = cv_image[ : , : , 3]
            np_image[ : , :width, 1] = cv_image[ : , : , 2]
            np_image[ : , :width, 2] = cv_image[ : , : , 1]
            np_image[ : , :width, 3] = cv_image[ : , : , 0]
        elif channel == 3:
            # assume BGR
            np_image = np.empty((height, new_width, channel), dtype=np.uint8)
            np_image[ : , :width, 0] = cv_image[ : , : , 2]
            np_image[ : , :width, 1] = cv_image[ : , : , 1]
            np_image[ : , :width, 2] = cv_image[ : , : , 0]
        elif channel == 1:
            # assume Y
            channel = 3
            np_image = np.empty((height, new_width, channel), dtype=np.uint8)
            np_image[ : , :width, 0] = cv_image[ : , : , 0]
            np_image[ : , :width, 1] = cv_image[ : , : , 0]
            np_image[ : , :width, 2] = cv_image[ : , : , 0]
        else:
            return
        bpl = new_width * channel
        qt_im = QtGui.QImage(np_image.data, width, height, bpl, fmt)
        # attach np_image so it isn't deleted until qt_im is
        qt_im._data = np_image
        return qt_im

    def transform(self, pixmap, orientation, inverse=False):
        orientation = (orientation or 1) - 1
        if not orientation:
            return pixmap
        # need to rotate and or reflect image
        transform = QtGui.QTransform()
        if orientation & 0b001:
            # reflect left-right
            transform = transform.scale(-1.0, 1.0)
        if orientation & 0b010:
            transform = transform.rotate(180.0)
        if orientation & 0b100:
            # transpose horizontal & vertical
            transform = QtGui.QTransform(0, 1, 1, 0, 1, 1) * transform
        if inverse:
            transform = transform.transposed()
        return pixmap.transformed(transform)

    @QtCore.pyqtSlot()
    @catch_all
    def regenerate_thumbnail(self):
        with Busy():
            # get Qt image first
            qt_im = QtGui.QImage(self.path)
            if self.file_type.startswith('video') and qt_im.isNull():
                # use OpenCV to read first frame
                qt_im = self.get_video_frame()
            if not qt_im or qt_im.isNull():
                logger.error('Cannot read %s image data from %s',
                             self.file_type, self.path)
                return
            # reorient if required
            if self.file_type in ('image/x-canon-cr2', 'image/x-nikon-nef'):
                qt_im = self.transform(
                    qt_im, self.metadata.orientation, inverse=True)
            w = qt_im.width()
            h = qt_im.height()
            # use Qt's scaling (not high quality) to pre-shrink very
            # large images, to avoid PIL "DecompressionBombWarning"
            if max(w, h) >= 6000:
                qt_im = qt_im.scaled(
                    6000, 6000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                w = qt_im.width()
                h = qt_im.height()
            # DCF spec says thumbnail must be 160 x 120 so pad picture
            # to 4:3 aspect ratio
            if w >= h:
                new_h = int(0.5 + (float(w * 3) / 4.0))
                new_w = int(0.5 + (float(h * 4) / 3.0))
                if new_h > h:
                    pad = (new_h - h) // 2
                    qt_im = qt_im.copy(0, -pad, w, new_h)
                elif new_w > w:
                    pad = (new_w - w) // 2
                    qt_im = qt_im.copy(-pad, 0, new_w, h)
                w, h = 160, 120
            else:
                new_h = int(0.5 + (float(w * 4) / 3.0))
                new_w = int(0.5 + (float(h * 3) / 4.0))
                if new_w > w:
                    pad = (new_w - w) // 2
                    qt_im = qt_im.copy(-pad, 0, new_w, h)
                elif new_h > h:
                    pad = (new_h - h) // 2
                    qt_im = qt_im.copy(0, -pad, w, new_h)
                w, h = 120, 160
            fmt = 'JPEG'
            if PIL:
                # convert Qt image to PIL image
                buf = QtCore.QBuffer()
                buf.open(QtCore.QIODevice.WriteOnly)
                qt_im.save(buf, 'PPM')
                data = BytesIO(buf.data().data())
                pil_im = PIL.open(data)
                # scale PIL image
                pil_im = pil_im.resize((w, h), PIL.ANTIALIAS)
                # save image to memory
                data = BytesIO()
                pil_im.save(data, fmt)
                data = data.getvalue()
            else:
                # scale Qt image - not as good quality as PIL
                qt_im = qt_im.scaled(
                    w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                # save image to memory
                buf = QtCore.QBuffer()
                buf.open(QtCore.QIODevice.WriteOnly)
                qt_im.save(buf, fmt)
                data = buf.data().data()
            # set thumbnail
            self.metadata.thumbnail = data, fmt, w, h
            # reload thumbnail
            self.load_thumbnail()

    @catch_all
    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)
        menu.addAction(self.tr('Reload metadata'), self.reload_metadata)
        menu.addAction(self.tr('Save metadata'), self.save_metadata)
        menu.addAction(self.tr('View changes'), self.diff_metadata)
        menu.addAction(self.tr('Regenerate thumbnail'), self.regenerate_thumbnail)
        action = menu.exec_(event.globalPos())

    @catch_all
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
        if event.modifiers() == Qt.ControlModifier:
            self.image_list.select_image(self, multiple_selection=True)
        elif event.modifiers() == Qt.ShiftModifier:
            self.image_list.select_image(self, extend_selection=True)
        elif not self.get_selected():
            # don't clear selection in case we're about to drag
            self.image_list.select_image(self)

    @catch_all
    def mouseReleaseEvent(self, event):
        if event.modifiers() not in (Qt.ControlModifier, Qt.ShiftModifier):
            # clear any multiple selection
            self.image_list.select_image(self)

    @catch_all
    def mouseMoveEvent(self, event):
        if not self.image_list.drag_icon:
            return
        if ((event.pos() - self.drag_start_pos).manhattanLength() <
                                    QtWidgets.QApplication.startDragDistance()):
            return
        paths = []
        for image in self.image_list.get_selected_images():
            paths.append(image.path)
        if not paths:
            return
        drag = QtGui.QDrag(self)
        # construct icon
        count = min(len(paths), 8)
        src_icon = self.image_list.drag_icon
        src_w = src_icon.width()
        src_h = src_icon.height()
        margin = (count - 1) * 4
        if count == 1:
            icon = src_icon
        else:
            icon = QtGui.QPixmap(src_w + margin, src_h + margin)
            icon.fill(Qt.transparent)
            with QtGui.QPainter(icon) as paint:
                for i in range(count):
                    paint.drawPixmap(
                        QtCore.QPoint(margin - (i * 4), i * 4), src_icon)
        drag.setPixmap(icon)
        if self.image_list.drag_hotspot:
            x, y = self.image_list.drag_hotspot
        else:
            x, y = src_w // 2, src_h
        drag.setHotSpot(QtCore.QPoint(x, y + margin))
        mimeData = QtCore.QMimeData()
        mimeData.setData(DRAG_MIMETYPE, repr(paths).encode('utf-8'))
        drag.setMimeData(mimeData)
        dropAction = drag.exec_(Qt.CopyAction)

    @catch_all
    def mouseDoubleClickEvent(self, event):
        webbrowser.open(self.path)

    @QtCore.pyqtSlot(bool)
    @catch_all
    def show_status(self, changed):
        status = ''
        # set 'geotagged' status
        if self.metadata.latlong:
            status += six.unichr(0x2690)
        # set 'unsaved' status
        if changed:
            status += six.unichr(0x26A1)
        self.status.setText(status)
        self._elide_name()
        if changed:
            self.image_list.new_metadata.emit(True)

    def _elide_name(self):
        self.status.adjustSize()
        elided_name = self.label.fontMetrics().elidedText(
            self.name, Qt.ElideLeft, self.thumb_size - self.status.width())
        self.label.setText(elided_name)

    def _set_thumb_size(self, thumb_size):
        self.thumb_size = thumb_size
        self.image.setFixedSize(self.thumb_size, self.thumb_size)
        self._elide_name()

    def set_thumb_size(self, thumb_size):
        self._set_thumb_size(thumb_size)
        self.load_thumbnail()

    def load_thumbnail(self):
        pixmap = QtGui.QPixmap()
        thumb = self.metadata.thumbnail
        if thumb:
            pixmap.loadFromData(thumb.data)
        if pixmap.isNull():
            self.image.setText(self.tr('No\nthumbnail\nin file'))
            return
        pixmap = self.transform(pixmap, self.metadata.orientation)
        self.image.setPixmap(
            pixmap.scaled(self.thumb_size, self.thumb_size,
                          Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_selected(self, value):
        self.selected = value
        if self.selected:
            self.setStyleSheet("#thumbnail {border: 2px solid red}")
        else:
            self.setStyleSheet("#thumbnail {border: 2px solid grey}")

    def get_selected(self):
        return self.selected


class ScrollArea(QtWidgets.QScrollArea):
    dropped_images = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super(ScrollArea, self).__init__(parent)
        self.multi_row = None
        self.set_multi_row(True)
        self.setWidgetResizable(True)
        self.setAcceptDrops(True)
        widget = QtWidgets.QWidget()
        self.thumbs = ThumbsLayout(scroll_area=self)
        widget.setLayout(self.thumbs)
        self.setWidget(widget)
        # adopt some layout methods
        self.add_widget = self.thumbs.addWidget
        self.remove_widget = self.thumbs.removeWidget

    def set_multi_row(self, multi_row):
        if multi_row:
            self.setMinimumHeight(0)
        else:
            scrollbar = self.horizontalScrollBar()
            self.setMinimumHeight(
                self.thumbs.sizeHint().height() + scrollbar.height())
        if multi_row == self.multi_row:
            return
        self.multi_row = multi_row
        if multi_row:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        else:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def ensureWidgetVisible(self, widget):
        left, top, right, bottom = self.thumbs.getContentsMargins()
        super(ScrollArea, self).ensureWidgetVisible(
            widget, max(left, right), max(top, bottom))

    @catch_all
    def dropEvent(self, event):
        file_list = []
        for uri in event.mimeData().urls():
            file_list.append(uri.toLocalFile())
        if file_list:
            self.dropped_images.emit(file_list)

    @catch_all
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('text/uri-list'):
            event.acceptProposedAction()

    @catch_all
    def resizeEvent(self, event):
        super(ScrollArea, self).resizeEvent(event)
        width = event.size().width()
        height = event.size().height()
        if not self.multi_row:
            scrollbar = self.verticalScrollBar()
            width -= scrollbar.width()
        scrollbar = self.horizontalScrollBar()
        if not scrollbar.isVisible():
            height -= scrollbar.height()
        self.thumbs.set_viewport_size(QtCore.QSize(width, height))


class ThumbsLayout(QtWidgets.QLayout):
    """Multi-row fixed-width or single-row variable-width grid of
    thumbnail widgets, according to height.

    """
    def __init__(self, scroll_area=None, **kw):
        super(ThumbsLayout, self).__init__(**kw)
        self.scroll_area = scroll_area
        self.item_list = []
        self.viewport_size = QtCore.QSize()
        self._do_layout(QtCore.QPoint(0, 0))

    def addItem(self, item):
        self.item_list.append(item)

    def horizontalSpacing(self):
        return 0

    def verticalSpacing(self):
        return 0

    def count(self):
        return len(self.item_list)

    def itemAt(self, idx):
        if idx < 0 or idx >= len(self.item_list):
            return None
        return self.item_list[idx]

    def takeAt(self, idx):
        if idx < 0 or idx >= len(self.item_list):
            return None
        return self.item_list.pop(idx)

    def expandingDirections(self):
        return 0

    def hasHeightForWidth(self):
        return False

    def setGeometry(self, rect):
        super(ThumbsLayout, self).setGeometry(rect)
        self._do_layout(rect.topLeft())

    def sizeHint(self):
        return self.size_hint

    def minimumSize(self):
        return self.size_hint

    def set_viewport_size(self, size):
        self.viewport_size = size
        self._do_layout(QtCore.QPoint(0, 0))

    def _do_layout(self, origin):
        left, top, right, bottom = self.getContentsMargins()
        width_hint = left + right
        height_hint = top + bottom
        if self.item_list:
            item_size = self.item_list[0].sizeHint()
            item_h = item_size.height()
            item_w = item_size.width()
            multi_row = self.viewport_size.height() - height_hint > item_h
            if multi_row:
                columns = max(
                    (self.viewport_size.width() - width_hint) // item_w, 1)
                rows = (len(self.item_list) + columns - 1) // columns
            else:
                columns = len(self.item_list)
                rows = 1
            width_hint += columns * item_w
            height_hint += rows * item_h
        self.size_hint = QtCore.QSize(width_hint, height_hint)
        if not self.item_list:
            return
        x = origin.x() + left
        y = origin.y() + top
        for n, item in enumerate(self.item_list):
            i, j = n % columns, n // columns
            item.setGeometry(QtCore.QRect(
                QtCore.QPoint(x + (i * item_w), y + (j * item_h)), item_size))
        self.scroll_area.set_multi_row(multi_row)


class ImageList(QtWidgets.QWidget):
    image_list_changed = QtCore.pyqtSignal()
    new_metadata = QtCore.pyqtSignal(bool)
    selection_changed = QtCore.pyqtSignal(list)
    sort_order_changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super(ImageList, self).__init__(parent)
        self.app = QtWidgets.QApplication.instance()
        self.drag_icon = None
        self.images = []
        self.last_selected = None
        self.selection_anchor = None
        self.thumb_size = int(
            self.app.config_store.get('controls', 'thumb_size', '80'))
        layout = QtWidgets.QGridLayout()
        layout.setSpacing(0)
        layout.setRowStretch(0, 1)
        layout.setColumnStretch(3, 1)
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        # thumbnail display
        self.scroll_area = ScrollArea()
        self.scroll_area.dropped_images.connect(self.open_file_list)
        layout.addWidget(self.scroll_area, 0, 0, 1, 6)
        QtWidgets.QShortcut(QtGui.QKeySequence.MoveToPreviousChar,
                        self.scroll_area, self.move_to_prev_thumb)
        QtWidgets.QShortcut(QtGui.QKeySequence.MoveToNextChar,
                        self.scroll_area, self.move_to_next_thumb)
        QtWidgets.QShortcut(QtGui.QKeySequence.MoveToStartOfLine,
                        self.scroll_area, self.move_to_first_thumb)
        QtWidgets.QShortcut(QtGui.QKeySequence.MoveToEndOfLine,
                        self.scroll_area, self.move_to_last_thumb)
        QtWidgets.QShortcut(QtGui.QKeySequence.SelectPreviousChar,
                        self.scroll_area, self.select_prev_thumb)
        QtWidgets.QShortcut(QtGui.QKeySequence.SelectNextChar,
                        self.scroll_area, self.select_next_thumb)
        QtWidgets.QShortcut(QtGui.QKeySequence.SelectAll,
                        self.scroll_area, self.select_all)
        # sort key selector
        layout.addWidget(QtWidgets.QLabel(self.tr('sort by: ')), 1, 0)
        self.sort_name = QtWidgets.QRadioButton(self.tr('file name'))
        self.sort_name.clicked.connect(self._new_sort_order)
        layout.addWidget(self.sort_name, 1, 1)
        self.sort_date = QtWidgets.QRadioButton(self.tr('date taken'))
        layout.addWidget(self.sort_date, 1, 2)
        self.sort_date.clicked.connect(self._new_sort_order)
        if eval(self.app.config_store.get('controls', 'sort_date', 'False')):
            self.sort_date.setChecked(True)
        else:
            self.sort_name.setChecked(True)
        # size selector
        layout.addWidget(QtWidgets.QLabel(self.tr('thumbnail size: ')), 1, 4)
        self.size_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.size_slider.setTracking(False)
        self.size_slider.setRange(4, 9)
        self.size_slider.setPageStep(1)
        self.size_slider.setValue(self.thumb_size / 20)
        self.size_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        width = self.size_slider.sizeHint().width()
        self.size_slider.setMinimumWidth(width * 7 // 4)
        self.size_slider.valueChanged.connect(self._new_thumb_size)
        layout.addWidget(self.size_slider, 1, 5)

    def set_drag_to_map(self, icon, hotspot=None):
        self.drag_icon = icon
        self.drag_hotspot = hotspot

    def get_image(self, path):
        for image in self.images:
            if image.path == path:
                return image
        return None

    def get_images(self):
        return self.images

    @catch_all
    def mousePressEvent(self, event):
        if self.scroll_area.underMouse():
            self._clear_selection()
            self.last_selected = None
            self.selection_anchor = None
            self.emit_selection()

    @QtCore.pyqtSlot(bool)
    @catch_all
    def open_files(self, checked):
        args = [
            self,
            self.tr('Open files'),
            self.app.config_store.get('paths', 'images', ''),
            self.tr("Images ({0});;Videos ({1});;All files (*)").format(
                ' '.join(['*.' + x for x in image_types()]),
                ' '.join(['*.' + x for x in video_types()]))
            ]
        if eval(self.app.config_store.get('pyqt', 'native_dialog', 'True')):
            pass
        elif qt_version_info >= (5, 0):
            args += [None, QtWidgets.QFileDialog.DontUseNativeDialog]
        else:
            args += [QtWidgets.QFileDialog.DontUseNativeDialog]
        path_list = QtWidgets.QFileDialog.getOpenFileNames(*args)
        if qt_version_info >= (5, 0):
            path_list = path_list[0]
        if not path_list:
            return
        # work around for Qt bug 33992
        # https://bugreports.qt-project.org/browse/QTBUG-33992
        if qt_version_info in ((4, 8, 4), (4, 8, 5)):
            path_list = list(map(unquote, path_list))
        self.open_file_list(path_list)

    @QtCore.pyqtSlot(list)
    @catch_all
    def open_file_list(self, path_list):
        with Busy():
            for path in path_list:
                self.open_file(path)
        self.done_opening(path_list[-1])

    def open_file(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return
        if self.get_image(path):
            # already opened this path
            return
        image = Image(path, self, thumb_size=self.thumb_size)
        self.images.append(image)
        self.show_thumbnail(image)

    def done_opening(self, path):
        self.app.config_store.set('paths', 'images', os.path.dirname(path))
        self._sort_thumbnails()

    def _date_key(self, image):
        result = image.metadata.date_taken
        if result is None:
            result = image.metadata.date_digitised
        if result is None:
            result = image.metadata.date_modified
        if result is None:
            # use file date as last resort
            result = datetime.fromtimestamp(os.path.getmtime(image.path))
        else:
            result = result.datetime
        # convert result to string and append path so photos with same
        # time stamp get sorted consistently
        result = result.strftime('%Y%m%d%H%M%S%f') + image.path
        return result

    @QtCore.pyqtSlot()
    @catch_all
    def _new_sort_order(self):
        self._sort_thumbnails()
        self.sort_order_changed.emit()

    def _sort_thumbnails(self):
        sort_date = self.sort_date.isChecked()
        self.app.config_store.set('controls', 'sort_date', str(sort_date))
        with Busy():
            if sort_date:
                self.images.sort(key=self._date_key)
            else:
                self.images.sort(key=lambda x: x.path)
            for image in self.images:
                self.show_thumbnail(image, False)
        if self.last_selected:
            self.app.processEvents()
            self.scroll_area.ensureWidgetVisible(self.last_selected)
        self.image_list_changed.emit()

    def show_thumbnail(self, image, live=True):
        self.scroll_area.add_widget(image)
        if live:
            self.app.processEvents()
        image.load_thumbnail()
        if live:
            self.app.processEvents()
            self.scroll_area.ensureWidgetVisible(image)
            self.app.processEvents()

    def close_files(self, all_files):
        if not self.unsaved_files_dialog(all_files=all_files):
            return
        if all_files:
            close_list = list(self.images)
        else:
            close_list = self.get_selected_images()
        if not close_list:
            return
        idx = self.images.index(close_list[0])
        for image in close_list:
            self.images.remove(image)
            self.scroll_area.remove_widget(image)
            image.setParent(None)
        if 0 <= idx < len(self.images):
            self.select_image(self.images[idx])
        else:
            self.last_selected = None
            self.selection_anchor = None
            self.emit_selection()
        self.image_list_changed.emit()

    @QtCore.pyqtSlot(bool)
    @catch_all
    def save_files(self, checked):
        self._save_files(self.images)

    def _save_files(self, images=[]):
        if_mode = eval(self.app.config_store.get('files', 'image', 'True'))
        sc_mode = self.app.config_store.get('files', 'sidecar', 'auto')
        force_iptc = eval(
            self.app.config_store.get('files', 'force_iptc', 'False'))
        keep_time = eval(
            self.app.config_store.get('files', 'preserve_timestamps', 'False'))
        if not images:
            images = self.images
        with Busy():
            for image in images:
                if keep_time:
                    file_times = image.file_times
                else:
                    file_times = None
                image.metadata.save(
                    if_mode=if_mode, sc_mode=sc_mode,
                    force_iptc=force_iptc, file_times=file_times)
        unsaved = False
        for image in self.images:
            if image.metadata.changed():
                unsaved = True
                break
        self.new_metadata.emit(unsaved)

    def unsaved_files_dialog(
            self, all_files=False, with_cancel=True, with_discard=True):
        """Return true if OK to continue with close or quit or whatever"""
        for image in self.images:
            if image.metadata.changed() and (all_files or image.selected):
                break
        else:
            return True
        dialog = QtWidgets.QMessageBox()
        dialog.setWindowTitle(self.tr('Photini: unsaved data'))
        dialog.setText(self.tr('<h3>Some images have unsaved metadata.</h3>'))
        dialog.setInformativeText(self.tr('Do you want to save your changes?'))
        dialog.setIcon(QtWidgets.QMessageBox.Warning)
        buttons = QtWidgets.QMessageBox.Save
        if with_cancel:
            buttons |= QtWidgets.QMessageBox.Cancel
        if with_discard:
            buttons |= QtWidgets.QMessageBox.Discard
        dialog.setStandardButtons(buttons)
        dialog.setDefaultButton(QtWidgets.QMessageBox.Save)
        result = dialog.exec_()
        if result == QtWidgets.QMessageBox.Save:
            self._save_files()
            return True
        return result == QtWidgets.QMessageBox.Discard

    def get_selected_images(self):
        selection = []
        for image in self.images:
            if image.get_selected():
                selection.append(image)
        return selection

    def emit_selection(self):
        self.selection_changed.emit(self.get_selected_images())

    def select_all(self):
        for image in self.images:
            image.set_selected(True)
        self.selection_anchor = None
        self.last_selected = None
        self.emit_selection()

    def move_to_prev_thumb(self):
        self._inc_selection(-1)

    def move_to_next_thumb(self):
        self._inc_selection(1)

    def move_to_first_thumb(self):
        self.select_image(self.images[0])

    def move_to_last_thumb(self):
        self.select_image(self.images[-1])

    def select_prev_thumb(self):
        self._inc_selection(-1, extend_selection=True)

    def select_next_thumb(self):
        self._inc_selection(1, extend_selection=True)

    def _inc_selection(self, inc, extend_selection=False):
        if self.last_selected:
            idx = self.images.index(self.last_selected)
            idx = (idx + inc) % len(self.images)
        else:
            idx = 0
        self.select_image(self.images[idx], extend_selection=extend_selection)

    @QtCore.pyqtSlot(int)
    @catch_all
    def _new_thumb_size(self, value):
        self.thumb_size = value * 20
        self.app.config_store.set('controls', 'thumb_size', str(self.thumb_size))
        for image in self.images:
            image.set_thumb_size(self.thumb_size)
        if self.last_selected:
            self.app.processEvents()
            self.scroll_area.ensureWidgetVisible(self.last_selected)

    def select_image(
            self, image, extend_selection=False, multiple_selection=False):
        self.scroll_area.ensureWidgetVisible(image)
        if extend_selection and self.selection_anchor:
            idx1 = self.images.index(self.selection_anchor)
            idx2 = self.images.index(self.last_selected)
            for i in range(min(idx1, idx2), max(idx1, idx2) + 1):
                self.images[i].set_selected(False)
            idx2 = self.images.index(image)
            for i in range(min(idx1, idx2), max(idx1, idx2) + 1):
                self.images[i].set_selected(True)
        elif multiple_selection:
            image.set_selected(not image.get_selected())
            self.selection_anchor = image
        else:
            self._clear_selection()
            image.set_selected(True)
            self.selection_anchor = image
        self.last_selected = image
        self.emit_selection()

    def select_images(self, images):
        self._clear_selection()
        if not images:
            self.last_selected = None
            self.selection_anchor = None
            self.emit_selection()
            return
        for image in images:
            image.set_selected(True)
            self.scroll_area.ensureWidgetVisible(image)
        self.selection_anchor = images[0]
        self.last_selected = images[-1]
        self.emit_selection()

    def _clear_selection(self):
        for image in self.images:
            if image.get_selected():
                image.set_selected(False)
