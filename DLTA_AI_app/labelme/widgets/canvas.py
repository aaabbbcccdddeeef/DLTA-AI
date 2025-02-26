from qtpy import QtCore
from qtpy import QtGui
from qtpy import QtWidgets

from labelme import QT5
from labelme.shape import Shape
import labelme.utils
import copy


# TODO(unknown):
# - [maybe] Find optimal epsilon value.


CURSOR_DEFAULT = QtCore.Qt.ArrowCursor
CURSOR_POINT = QtCore.Qt.PointingHandCursor
CURSOR_DRAW = QtCore.Qt.CrossCursor
CURSOR_MOVE = QtCore.Qt.ClosedHandCursor
CURSOR_GRAB = QtCore.Qt.OpenHandCursor


class Canvas(QtWidgets.QWidget):

    zoomRequest = QtCore.Signal(int, QtCore.QPoint)
    scrollRequest = QtCore.Signal(int, int)
    newShape = QtCore.Signal()
    selectionChanged = QtCore.Signal(list)
    shapeMoved = QtCore.Signal()
    drawingPolygon = QtCore.Signal(bool)
    edgeSelected = QtCore.Signal(bool, object)
    vertexSelected = QtCore.Signal(bool)
    # SAM signals
    pointAdded = QtCore.Signal()
    samFinish = QtCore.Signal()
    # reset = QtCore.Signal()
    # interrupted = QtCore.Signal()
    APPrefresh = QtCore.Signal(bool)

    CREATE, EDIT = 0, 1
    CREATE, EDIT = 0, 1

    # polygon, rectangle, line, or point
    _createMode = "polygon"

    _fill_drawing = False

    def __init__(self, *args, **kwargs):
        self.epsilon = kwargs.pop("epsilon", 10.0)
        self.double_click = kwargs.pop("double_click", "close")
        if self.double_click not in [None, "close"]:
            raise ValueError(
                "Unexpected value for double_click event: {}".format(
                    self.double_click
                )
            )
        self.num_backups = kwargs.pop("num_backups", 10)
        super(Canvas, self).__init__(*args, **kwargs)
        # Initialise local state.
        self.mode = self.EDIT
        self.shapes = []
        # Segment anything (SAM) attributes
        self.SAM_mode = ""
        self.SAM_coordinates = []
        self.SAM_rect = []
        self.SAM_rects = []
        self.SAM_painter = QtGui.QPainter()
        self.SAM_current = None
        # mouse tracking
        self.show_cross_line = True
        self.h_w_of_image = [-1, -1]
        # Waiting window
        self.is_loading = False
        self.loading_angle = 0
        self.loading_text = "Loading..."
        # tracking area
        self.tracking_area = ""
        self.tracking_area_polygon = []
        
        self.current_annotation_mode = ""

        self.shapesBackups = []
        self.current = None
        self.selectedShapes = []  # save the selected shapes here
        self.selectedShapesCopy = []
        # self.line represents:
        #   - createMode == 'polygon': edge from last point to current
        #   - createMode == 'rectangle': diagonal line of the rectangle
        #   - createMode == 'line': the line
        #   - createMode == 'point': the point
        self.line = Shape()
        self.prevPoint = QtCore.QPoint()
        self.prevMovePoint = QtCore.QPoint()
        self.offsets = QtCore.QPoint(), QtCore.QPoint()
        self.scale = 1.0
        self.pixmap = QtGui.QPixmap()
        self.visible = {}
        self._hideBackround = False
        self.hideBackround = False
        self.hShape = None
        self.prevhShape = None
        self.hVertex = None
        self.prevhVertex = None
        self.hEdge = None
        self.prevhEdge = None
        self.movingShape = False
        self._painter = QtGui.QPainter()
        self._cursor = CURSOR_DEFAULT

        # Menus:
        # 0: right-click without selection and dragging of shapes
        # 1: right-click with selection and dragging of shapes
        self.menus = (QtWidgets.QMenu(), QtWidgets.QMenu())
        # Set widget options.
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.WheelFocus)

    def fillDrawing(self):
        return self._fill_drawing

    def setFillDrawing(self, value):
        self._fill_drawing = value

    @property
    def createMode(self):
        return self._createMode

    @createMode.setter
    def createMode(self, value):
        if value not in [
            "polygon",
            "rectangle",
            "circle",
            "line",
            "point",
            "linestrip",
        ]:
            raise ValueError("Unsupported createMode: %s" % value)
        self._createMode = value

    def storeShapes(self):
        shapesBackup = []
        for shape in self.shapes:
            shapesBackup.append(shape.copy())
        if len(self.shapesBackups) > self.num_backups:
            self.shapesBackups = self.shapesBackups[-self.num_backups - 1:]
        self.shapesBackups.append(shapesBackup)

    @property
    def isShapeRestorable(self):
        # We save the state AFTER each edit (not before) so for an
        # edit to be undoable, we expect the CURRENT and the PREVIOUS state
        # to be in the undo stack.
        if len(self.shapesBackups) < 2:
            return False
        return True

    def restoreShape(self):
        # This does _part_ of the job of restoring shapes.
        # The complete process is also done in app.py::undoShapeEdit
        # and app.py::loadShapes and our own Canvas::loadShapes function.
        if not self.isShapeRestorable:
            return
        self.shapesBackups.pop()  # latest

        # The application will eventually call Canvas.loadShapes which will
        # push this right back onto the stack.
        shapesBackup = self.shapesBackups.pop()
        self.shapes = shapesBackup
        self.selectedShapes = []
        for shape in self.shapes:
            shape.selected = False
        self.update()

    def enterEvent(self, ev):
        self.overrideCursor(self._cursor)

    def leaveEvent(self, ev):
        self.unHighlight()
        self.restoreCursor()

    def focusOutEvent(self, ev):
        self.restoreCursor()

    def isVisible(self, shape):
        return self.visible.get(shape, True)

    def drawing(self):
        return self.mode == self.CREATE

    def editing(self):
        return self.mode == self.EDIT

    def setEditing(self, value=True):
        self.mode = self.EDIT if value else self.CREATE
        if not value:  # Create
            self.unHighlight()
            self.deSelectShape()

    def unHighlight(self):
        if self.hShape:
            self.hShape.highlightClear()
            self.update()
        self.prevhShape = self.hShape
        self.prevhVertex = self.hVertex
        self.prevhEdge = self.hEdge
        self.hShape = self.hVertex = self.hEdge = None

    def selectedVertex(self):
        return self.hVertex is not None

    def set_show_cross_line(self, enabled):
        """Set cross line visibility"""
        self.show_cross_line = enabled
        self.update()

    def mouseMoveEvent(self, ev):
        """Update line with last point and current coordinates."""
        try:
            if QT5:
                pos = self.transformPos(ev.localPos())
            else:
                pos = self.transformPos(ev.posF())
        except AttributeError:
            return

        self.prevMovePoint = pos
        self.repaint()
        self.restoreCursor()

        # Polygon drawing.
        if self.drawing():
            self.line.shape_type = self.createMode

            self.overrideCursor(CURSOR_DRAW)
            if not self.current:
                return

            if self.outOfPixmap(pos):
                # Don't allow the user to draw outside the pixmap.
                # Project the point to the pixmap's edges.
                pos = self.intersectionPoint(self.current[-1], pos)
            elif (
                len(self.current) > 1
                and self.createMode == "polygon"
                and self.closeEnough(pos, self.current[0])
            ):
                # Attract line to starting point and
                # colorise to alert the user.
                pos = self.current[0]
                self.overrideCursor(CURSOR_POINT)
                self.current.highlightVertex(0, Shape.NEAR_VERTEX)
            if self.createMode in ["polygon", "linestrip"]:
                self.line[0] = self.current[-1]
                self.line[1] = pos
            elif self.createMode == "rectangle":
                self.line.points = [self.current[0], pos]
                self.line.close()
            elif self.createMode == "circle":
                self.line.points = [self.current[0], pos]
                self.line.shape_type = "circle"
            elif self.createMode == "line":
                self.line.points = [self.current[0], pos]
                self.line.close()
            elif self.createMode == "point":
                self.line.points = [self.current[0]]
                self.line.close()
            self.repaint()
            self.current.highlightClear()
            return

        # Polygon copy moving.
        if QtCore.Qt.RightButton & ev.buttons():
            if self.selectedShapesCopy and self.prevPoint:
                self.overrideCursor(CURSOR_MOVE)
                self.boundedMoveShapes(self.selectedShapesCopy, pos)
                self.repaint()
            elif self.selectedShapes:
                self.selectedShapesCopy = [
                    s.copy() for s in self.selectedShapes
                ]
                self.repaint()
            return

        # Polygon/Vertex moving.
        if QtCore.Qt.LeftButton & ev.buttons():
            if self.selectedVertex():
                self.boundedMoveVertex(pos)
                self.repaint()
                self.movingShape = True
            elif self.selectedShapes and self.prevPoint:
                self.overrideCursor(CURSOR_MOVE)
                self.boundedMoveShapes(self.selectedShapes, pos)
                self.repaint()
                self.movingShape = True
            return

        # Just hovering over the canvas, 2 possibilities:
        # - Highlight shapes
        # - Highlight vertex
        # Update shape/vertex fill and tooltip value accordingly.
        self.setToolTip(self.tr("Image"))
        for shape in reversed([s for s in self.shapes if self.isVisible(s)]):
            # Look for a nearby vertex to highlight. If that fails,
            # check if we happen to be inside a shape.
            index = shape.nearestVertex(pos, self.epsilon / self.scale)
            index_edge = shape.nearestEdge(pos, self.epsilon / self.scale)
            if index is not None:
                if self.selectedVertex():
                    self.hShape.highlightClear()
                self.prevhVertex = self.hVertex = index
                self.prevhShape = self.hShape = shape
                self.prevhEdge = self.hEdge = index_edge
                shape.highlightVertex(index, shape.MOVE_VERTEX)
                self.overrideCursor(CURSOR_POINT)
                self.setToolTip(self.tr("Click & drag to move point"))
                self.setStatusTip(self.toolTip())
                self.update()
                break
            elif shape.containsPoint(pos):
                if self.selectedVertex():
                    self.hShape.highlightClear()
                self.prevhVertex = self.hVertex
                self.hVertex = None
                self.prevhShape = self.hShape = shape
                self.prevhEdge = self.hEdge = index_edge
                self.setToolTip(
                    self.tr("Click & drag to move shape '%s'") % shape.label
                )
                # conf = shape.content (to two decimal places)

                if shape.group_id != None and self.current_annotation_mode == 'video':
                    self.setToolTip(
                        self.tr(f'ID {str(shape.group_id)} {shape.label} {shape.content}'))
                else:
                    self.setToolTip(self.tr(f'{shape.label} {shape.content}'))

                self.setStatusTip(self.toolTip())
                self.overrideCursor(CURSOR_GRAB)
                self.update()
                break
        else:  # Nothing found, clear highlights, reset state.
            self.unHighlight()
        self.edgeSelected.emit(self.hEdge is not None, self.hShape)
        self.vertexSelected.emit(self.hVertex is not None)

    def addPointToEdge(self):
        shape = self.prevhShape
        index = self.prevhEdge
        point = self.prevMovePoint
        if shape is None or index is None or point is None:
            return
        shape.insertPoint(index, point)
        shape.highlightVertex(index, shape.MOVE_VERTEX)
        self.hShape = shape
        self.hVertex = index
        self.hEdge = None
        self.movingShape = True

    def removeSelectedPoint(self):
        shape = self.prevhShape
        point = self.prevMovePoint
        if shape is None or point is None:
            return
        index = shape.nearestVertex(point, self.epsilon)
        shape.removePoint(index)
        # shape.highlightVertex(index, shape.MOVE_VERTEX)
        self.hShape = shape
        self.hVertex = None
        self.hEdge = None
        self.movingShape = True  # Save changes

    def correct_pos_for_SAM(self, pos):
        x = pos.x()
        y = pos.y()
        h = self.h_w_of_image[0]
        w = self.h_w_of_image[1]
        x = max(0, x)
        y = max(0, y)
        x = min(w, x)
        y = min(h, y)
        res = QtCore.QPointF(x, y)
        return res

    def mousePressEvent(self, ev):
        if QT5:
            pos = self.transformPos(ev.localPos())
        else:
            pos = self.transformPos(ev.posF())
        # print("mousePressEvent", pos, "self.mode", self.mode, "self.createMode", self.createMode, "self.drawing()", self.drawing(), "self.editing()", self.editing())
        if ev.button() == QtCore.Qt.LeftButton:
            if self.drawing() and self.SAM_mode == "":
                if self.current:
                    # Add point to existing shape.
                    if self.createMode == "polygon":
                        self.current.addPoint(self.line[1])
                        self.line[0] = self.current[-1]
                        if self.current.isClosed():
                            self.finalise()
                    elif self.createMode in ["rectangle", "circle", "line"]:
                        assert len(self.current.points) == 1
                        self.current.points = self.line.points
                        self.finalise()
                    elif self.createMode == "linestrip":
                        self.current.addPoint(self.line[1])
                        self.line[0] = self.current[-1]
                        if int(ev.modifiers()) == QtCore.Qt.ControlModifier:
                            self.finalise()
                elif not self.outOfPixmap(pos):
                    # Create new shape.
                    self.current = Shape(shape_type=self.createMode)
                    self.current.addPoint(pos)
                    if self.createMode == "point":
                        self.finalise()
                    else:
                        if self.createMode == "circle":
                            self.current.shape_type = "circle"
                        self.line.points = [pos, pos]
                        self.setHiding()
                        self.drawingPolygon.emit(True)
                        self.update()
            elif self.SAM_mode == "add point":
                if not self.outOfPixmap(pos):
                    # add the coordinates and the label (1 forground 0 background)
                    self.SAM_coordinates.append([pos.x(), pos.y(), 1])
                    # print(self.SAM_coordinates)
                    self.pointAdded.emit()

            elif self.SAM_mode == 'remove point':
                if not self.outOfPixmap(pos):
                    # add the coordinates and the label (1 forground 0 background)
                    self.SAM_coordinates.append([pos.x(), pos.y(), 0])
                    # print(self.SAM_coordinates)
                    self.pointAdded.emit()
            elif self.SAM_mode == 'select rect':
                self.SAM_rect.append(self.correct_pos_for_SAM(pos))
                if len(self.SAM_rect) == 2:
                    print("do smth")
                    # self.SAM_rects.append(self.SAM_rect)
                    self.SAM_rects = [self.SAM_rect]
                    self.pointAdded.emit()
                    self.SAM_rect = []
            
            elif self.tracking_area == "drawing":
                if not self.outOfPixmap(pos):
                    self.tracking_area_polygon.append([pos.x(), pos.y()])
            
            # the other is editing mode
            else:
                group_mode = int(ev.modifiers()) == QtCore.Qt.ControlModifier
                self.selectShapePoint(pos, multiple_selection_mode=group_mode)
                self.prevPoint = pos
                self.repaint()
        elif ev.button() == QtCore.Qt.RightButton and self.editing():
            group_mode = int(ev.modifiers()) == QtCore.Qt.ControlModifier
            self.selectShapePoint(pos, multiple_selection_mode=group_mode)
            self.prevPoint = pos
            self.repaint()

    def handle_right_click(self, menu):
        try:
            setEnabledd = menu.actions()[7].text() == "Edit &Label" and menu.actions()[7].isEnabled()
            # if menu.actions()[8].text() == "&AI Enhance":
            #     menu.actions()[8].setEnabled(setEnabledd)
            if menu.actions()[10].text() == "&Mark as key":
                menu.actions()[10].setEnabled(setEnabledd)
            if menu.actions()[11].text() == "&Scale":
                menu.actions()[11].setEnabled(setEnabledd)
        except:
            pass
        return menu

    def mouseReleaseEvent(self, ev):
        if QT5:
            pos = self.transformPos(ev.localPos())
        else:
            pos = self.transformPos(ev.posF())
        # print("mouseReleaseEvent", "self.mode", self.mode, "self.createMode", self.createMode, "self.drawing()", self.drawing(), "self.editing()", self.editing())
        if ev.button() == QtCore.Qt.RightButton:
            menu = self.menus[len(self.selectedShapesCopy) > 0]
            menu = self.handle_right_click(menu)
            self.restoreCursor()
            if (
                not menu.exec_(self.mapToGlobal(ev.pos()))
                and self.selectedShapesCopy
            ):
                # Cancel the move by deleting the shadow copy.
                self.selectedShapesCopy = []
                self.repaint()
        elif ev.button() == QtCore.Qt.LeftButton and self.selectedShapes:
            self.overrideCursor(CURSOR_GRAB)
            if (
                self.editing()
                and int(ev.modifiers()) == QtCore.Qt.ShiftModifier
            ):
                # Add point to line if: left-click + SHIFT on a line segment
                self.addPointToEdge()
        elif ev.button() == QtCore.Qt.LeftButton and self.selectedVertex():
            if (
                self.editing()
                and int(ev.modifiers()) == QtCore.Qt.ShiftModifier
            ):
                # Delete point if: left-click + SHIFT on a point
                self.removeSelectedPoint()
        elif ev.button() == QtCore.Qt.LeftButton and len(self.SAM_rect) == 1:
            if abs(pos.x() - self.SAM_rect[0].x()) + abs(pos.y() - self.SAM_rect[0].y()) > 50:
                self.SAM_rect.append(self.correct_pos_for_SAM(pos))
                print("do smth")
                # self.SAM_rects.append(self.SAM_rect)
                self.SAM_rects = [self.SAM_rect]
                self.pointAdded.emit()
                self.SAM_rect = []

        if self.movingShape and self.hShape:
            index = self.shapes.index(self.hShape)
            if (
                self.shapesBackups[-1][index].points
                != self.shapes[index].points
            ):
                self.storeShapes()
                self.shapeMoved.emit()

            self.movingShape = False
            self.APPrefresh.emit(True)

    def endMove(self, copy):
        assert self.selectedShapes and self.selectedShapesCopy
        assert len(self.selectedShapesCopy) == len(self.selectedShapes)
        if copy:
            for i, shape in enumerate(self.selectedShapesCopy):
                self.shapes.append(shape)
                self.selectedShapes[i].selected = False
                self.selectedShapes[i] = shape
        else:
            for i, shape in enumerate(self.selectedShapesCopy):
                self.selectedShapes[i].points = shape.points
        self.selectedShapesCopy = []
        self.repaint()
        self.storeShapes()
        return True

    def hideBackroundShapes(self, value):
        self.hideBackround = value
        if self.selectedShapes:
            # Only hide other shapes if there is a current selection.
            # Otherwise the user will not be able to select a shape.
            self.setHiding(True)
            self.update()

    def setHiding(self, enable=True):
        self._hideBackround = self.hideBackround if enable else False

    def canCloseShape(self):
        return self.drawing() and self.current and len(self.current) > 2

    def mouseDoubleClickEvent(self, ev):
        # We need at least 4 points here, since the mousePress handler
        # adds an extra one before this handler is called.
        if (
            self.double_click == "close"
            and self.canCloseShape()
            and len(self.current) > 3
        ):
            self.current.popPoint()
            self.finalise()
            
        if self.tracking_area == "drawing":
            self.tracking_area = "drawn"

    def selectShapes(self, shapes):
        self.setHiding()
        self.selectionChanged.emit(shapes)
        self.update()

    def selectShapePoint(self, point, multiple_selection_mode):
        """Select the first shape created which contains this point."""
        if self.selectedVertex():  # A vertex is marked for selection.
            index, shape = self.hVertex, self.hShape
            shape.highlightVertex(index, shape.MOVE_VERTEX)
        else:
            for shape in reversed(self.shapes):
                if self.isVisible(shape) and shape.containsPoint(point):
                    self.calculateOffsets(shape, point)
                    self.setHiding()
                    if multiple_selection_mode:
                        if shape not in self.selectedShapes:
                            self.selectionChanged.emit(
                                self.selectedShapes + [shape]
                            )
                    else:
                        self.selectionChanged.emit([shape])
                    return
        self.deSelectShape()

    def calculateOffsets(self, shape, point):
        rect = shape.boundingRect()
        x1 = rect.x() - point.x()
        y1 = rect.y() - point.y()
        x2 = (rect.x() + rect.width() - 1) - point.x()
        y2 = (rect.y() + rect.height() - 1) - point.y()
        self.offsets = QtCore.QPoint(x1, y1), QtCore.QPoint(x2, y2)

    def boundedMoveVertex(self, pos):
        index, shape = self.hVertex, self.hShape
        point = shape[index]
        if self.outOfPixmap(pos):
            pos = self.intersectionPoint(point, pos)
        shape.moveVertexBy(index, pos - point)

    def boundedMoveShapes(self, shapes, pos):
        if self.outOfPixmap(pos):
            return False  # No need to move
        o1 = pos + self.offsets[0]
        if self.outOfPixmap(o1):
            pos -= QtCore.QPoint(min(0, o1.x()), min(0, o1.y()))
        o2 = pos + self.offsets[1]
        if self.outOfPixmap(o2):
            pos += QtCore.QPoint(
                min(0, self.pixmap.width() - o2.x()),
                min(0, self.pixmap.height() - o2.y()),
            )
        # XXX: The next line tracks the new position of the cursor
        # relative to the shape, but also results in making it
        # a bit "shaky" when nearing the border and allows it to
        # go outside of the shape's area for some reason.
        # self.calculateOffsets(self.selectedShapes, pos)
        dp = pos - self.prevPoint
        if dp:
            for shape in shapes:
                shape.moveBy(dp)
            self.prevPoint = pos
            return True
        return False

    def deSelectShape(self):
        if self.selectedShapes:
            self.setHiding(False)
            self.selectionChanged.emit([])
            self.update()

    def deleteSelected(self):
        deleted_shapes = []
        if self.selectedShapes:
            for shape in self.selectedShapes:
                self.shapes.remove(shape)
                deleted_shapes.append(shape)
            self.storeShapes()
            self.selectedShapes = []
            self.update()
        return deleted_shapes

    def deleteShape(self, shape):
        if shape in self.selectedShapes:
            self.selectedShapes.remove(shape)
        if shape in self.shapes:
            self.shapes.remove(shape)
        self.storeShapes()
        self.update()

    def copySelectedShapes(self):
        if self.selectedShapes:
            self.selectedShapesCopy = [s.copy() for s in self.selectedShapes]
            self.boundedShiftShapes(self.selectedShapesCopy)
            self.endMove(copy=True)
        return self.selectedShapes

    def boundedShiftShapes(self, shapes):
        # Try to move in one direction, and if it fails in another.
        # Give up if both fail.
        point = shapes[0][0]
        offset = QtCore.QPoint(2.0, 2.0)
        self.offsets = QtCore.QPoint(), QtCore.QPoint()
        self.prevPoint = point
        if not self.boundedMoveShapes(shapes, point - offset):
            self.boundedMoveShapes(shapes, point + offset)

    def paintEvent(self, event):
        if not self.pixmap and not self.is_loading:
            return super(Canvas, self).paintEvent(event)

        p = self._painter
        p.begin(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.HighQualityAntialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        p.scale(self.scale, self.scale)
        p.translate(self.offsetToCenter())

        p.drawPixmap(0, 0, self.pixmap)
        Shape.scale = self.scale

        # Draw loading/waiting screen
        if self.is_loading:
            # Draw a semi-transparent rectangle
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 100))
            p.drawRect(self.pixmap.rect())

            # Draw a spinning wheel
            p.setPen(QtGui.QColor(255, 255, 255))
            p.setBrush(QtCore.Qt.NoBrush)
            p.save()
            p.translate(self.pixmap.width() / 2, self.pixmap.height() / 2 - 50)
            p.rotate(self.loading_angle)
            p.drawEllipse(-20, -20, 40, 40)
            p.drawLine(0, 0, 0, -20)
            p.restore()
            self.loading_angle += 5
            if self.loading_angle >= 360:
                self.loading_angle = 0

            # Draw the loading text
            p.setPen(QtGui.QColor(255, 255, 255))
            try:
                fontsize = self.pixmap.width() / 50
                p.setFont(QtGui.QFont("Arial", fontsize))
            except:
                p.setFont(QtGui.QFont("Arial", 20))
            p.drawText(
                self.pixmap.rect(),
                QtCore.Qt.AlignCenter,
                self.loading_text,
            )
            p.end()
            self.update()
            return

        for shape in self.shapes:
            if (shape.selected or not self._hideBackround) and self.isVisible(
                shape
            ):
                shape.fill = shape.selected or shape == self.hShape
                shape.paint(p)
        if self.current:
            self.current.paint(p)
            self.line.paint(p)
        if self.selectedShapesCopy:
            for s in self.selectedShapesCopy:
                s.paint(p)

        if (
            self.fillDrawing()
            and self.createMode == "polygon"
            and self.current is not None
            and len(self.current.points) >= 2
        ):
            drawing_shape = self.current.copy()
            drawing_shape.addPoint(self.line[1])
            drawing_shape.fill = True
            drawing_shape.paint(p)

        # Draw mouse coordinates
        if self.show_cross_line:
            pen = QtGui.QPen(
                QtGui.QColor("#00FF00"),
                max(1, int(round(2.0 / Shape.scale))),
                QtCore.Qt.DashLine,
            )
            p.setPen(pen)
            p.setOpacity(0.5)
            p.drawLine(
                QtCore.QPointF(self.prevMovePoint.x(), 0),
                QtCore.QPointF(self.prevMovePoint.x(), self.pixmap.height()),
            )
            p.drawLine(
                QtCore.QPointF(0, self.prevMovePoint.y()),
                QtCore.QPointF(self.pixmap.width(), self.prevMovePoint.y()),
            )

        # draw SAM rectangle
        if len(self.SAM_rect) == 1:
            pen = QtGui.QPen(
                QtGui.QColor("#FF0000"),
                2 * max(1, int(round(2.0 / Shape.scale))),
                QtCore.Qt.SolidLine,
            )
            p.setPen(pen)
            p.setOpacity(0.8)

            point1 = [self.SAM_rect[0].x(), self.SAM_rect[0].y()]
            corrected = self.correct_pos_for_SAM(self.prevMovePoint)
            point2 = [corrected.x(), corrected.y()]
            x1 = min(point1[0], point2[0])
            y1 = min(point1[1], point2[1])
            w = abs(point1[0] - point2[0])
            h = abs(point1[1] - point2[1])
            p.drawRect(x1, y1, w, h)

        # draw SAM points
        if len(self.SAM_coordinates) != 0:
            for point in self.SAM_coordinates:
                color = "#FF0000" if point[2] == 0 else "#19EB25"
                pen = QtGui.QPen(
                    QtGui.QColor(color),
                    5 * max(1, int(round(2.0 / Shape.scale))),
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
                p.setPen(pen)
                p.setOpacity(0.8)
                p.drawPoint(point[0], point[1])

        if len(self.SAM_rects) != 0:
            box = self.SAM_rects[-1]
            pen = QtGui.QPen(
                QtGui.QColor("#2D7CFA"),
                2 * max(1, int(round(2.0 / Shape.scale))),
                QtCore.Qt.SolidLine,
            )
            p.setPen(pen)
            p.setOpacity(0.8)

            point1 = [box[0].x(), box[0].y()]
            point2 = [box[1].x(), box[1].y()]
            x1 = min(point1[0], point2[0])
            y1 = min(point1[1], point2[1])
            w = abs(point1[0] - point2[0])
            h = abs(point1[1] - point2[1])
            p.drawRect(x1, y1, w, h)

        if self.tracking_area != "":
            pen = QtGui.QPen(
                QtGui.QColor("#FF0000"),
                2 * max(1, int(round(2.0 / Shape.scale))),
                QtCore.Qt.SolidLine,
            )
            p.setPen(pen)
            p.setOpacity(0.1)
            p.setBrush(QtGui.QColor("#FF0000"));
            if len(self.tracking_area_polygon) > 0:
                point2 = [self.prevMovePoint.x(), self.prevMovePoint.y()]
                total = copy.deepcopy(self.tracking_area_polygon)
                if self.tracking_area == "drawing":
                    total.append(point2)
                total = [ QtCore.QPoint(p[0], p[1]) for p in total]
                p.drawPolygon(total)
                p.setOpacity(0.7)
                if self.tracking_area == "drawing":
                    p.drawPolyline(total)
                else:
                    total.append(total[0])
                    p.drawPolyline(total)


        p.end()

    def transformPos(self, point):
        """Convert from widget-logical coordinates to painter-logical ones."""
        return point / self.scale - self.offsetToCenter()

    def offsetToCenter(self):
        s = self.scale
        area = super(Canvas, self).size()
        w, h = self.pixmap.width() * s, self.pixmap.height() * s
        aw, ah = area.width(), area.height()
        x = (aw - w) / (2 * s) if aw > w else 0
        y = (ah - h) / (2 * s) if ah > h else 0
        return QtCore.QPoint(x, y)

    def outOfPixmap(self, p):
        w, h = self.pixmap.width(), self.pixmap.height()
        return not (0 <= p.x() <= w - 1 and 0 <= p.y() <= h - 1)

    def finalise(self, SAM_SHAPE=False):
        if SAM_SHAPE:
            assert self.SAM_current
            self.SAM_current.close()
            # self.shapes.append(self.SAM_current)
            self.storeShapes()
            self.SAM_current = None
            self.setHiding(False)
            self.newShape.emit()
            self.update()
        else:
            assert self.current
            self.current.close()
            self.shapes.append(self.current)
            self.storeShapes()
            self.current = None
            self.setHiding(False)
            self.newShape.emit()
            self.update()

    def closeEnough(self, p1, p2):
        # d = distance(p1 - p2)
        # m = (p1-p2).manhattanLength()
        # print "d %.2f, m %d, %.2f" % (d, m, d - m)
        # divide by scale to allow more precision when zoomed in
        return labelme.utils.distance(p1 - p2) < (self.epsilon / self.scale)

    def intersectionPoint(self, p1, p2):
        # Cycle through each image edge in clockwise fashion,
        # and find the one intersecting the current line segment.
        # http://paulbourke.net/geometry/lineline2d/
        size = self.pixmap.size()
        points = [
            (0, 0),
            (size.width() - 1, 0),
            (size.width() - 1, size.height() - 1),
            (0, size.height() - 1),
        ]
        # x1, y1 should be in the pixmap, x2, y2 should be out of the pixmap
        x1 = min(max(p1.x(), 0), size.width() - 1)
        y1 = min(max(p1.y(), 0), size.height() - 1)
        x2, y2 = p2.x(), p2.y()
        d, i, (x, y) = min(self.intersectingEdges((x1, y1), (x2, y2), points))
        x3, y3 = points[i]
        x4, y4 = points[(i + 1) % 4]
        if (x, y) == (x1, y1):
            # Handle cases where previous point is on one of the edges.
            if x3 == x4:
                return QtCore.QPoint(x3, min(max(0, y2), max(y3, y4)))
            else:  # y3 == y4
                return QtCore.QPoint(min(max(0, x2), max(x3, x4)), y3)
        return QtCore.QPoint(x, y)

    def intersectingEdges(self, point1, point2, points):
        """Find intersecting edges.

        For each edge formed by `points', yield the intersection
        with the line segment `(x1,y1) - (x2,y2)`, if it exists.
        Also return the distance of `(x2,y2)' to the middle of the
        edge along with its index, so that the one closest can be chosen.
        """
        (x1, y1) = point1
        (x2, y2) = point2
        for i in range(4):
            x3, y3 = points[i]
            x4, y4 = points[(i + 1) % 4]
            denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
            nua = (x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)
            nub = (x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)
            if denom == 0:
                # This covers two cases:
                #   nua == nub == 0: Coincident
                #   otherwise: Parallel
                continue
            ua, ub = nua / denom, nub / denom
            if 0 <= ua <= 1 and 0 <= ub <= 1:
                x = x1 + ua * (x2 - x1)
                y = y1 + ua * (y2 - y1)
                m = QtCore.QPoint((x3 + x4) / 2, (y3 + y4) / 2)
                d = labelme.utils.distance(m - QtCore.QPoint(x2, y2))
                yield d, i, (x, y)

    # These two, along with a call to adjustSize are required for the
    # scroll area.
    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        if self.pixmap:
            return self.scale * self.pixmap.size()
        return super(Canvas, self).minimumSizeHint()

    def wheelEvent(self, ev):
        if QT5:
            mods = ev.modifiers()
            delta = ev.angleDelta()
            if QtCore.Qt.ControlModifier == int(mods):
                # with Ctrl/Command key
                # zoom
                self.zoomRequest.emit(delta.y(), ev.pos())
            else:
                # scroll
                self.scrollRequest.emit(delta.x(), QtCore.Qt.Horizontal)
                self.scrollRequest.emit(delta.y(), QtCore.Qt.Vertical)
        else:
            if ev.orientation() == QtCore.Qt.Vertical:
                mods = ev.modifiers()
                if QtCore.Qt.ControlModifier == int(mods):
                    # with Ctrl/Command key
                    self.zoomRequest.emit(ev.delta(), ev.pos())
                else:
                    self.scrollRequest.emit(
                        ev.delta(),
                        QtCore.Qt.Horizontal
                        if (QtCore.Qt.ShiftModifier == int(mods))
                        else QtCore.Qt.Vertical,
                    )
            else:
                self.scrollRequest.emit(ev.delta(), QtCore.Qt.Horizontal)
        ev.accept()

    def keyPressEvent(self, ev):
        key = ev.key()
        # if key == QtCore.Qt.Key_Escape:
        #     self.interrupted.emit()
        #     if self.SAM_mode != "":
        #         self.reset.emit()
        #     if self.current:
        #         self.current = None
        #         self.drawingPolygon.emit(False)
        #         self.update()
        # if key == QtCore.Qt.Key_Return and self.canCloseShape():
        #     self.finalise()
        if key == QtCore.Qt.Key_Return:
            if self.SAM_mode != "":
                self.samFinish.emit()
            elif self.tracking_area:
                self.tracking_area = "drawn"
                self.update()
            elif self.canCloseShape():
                self.finalise()
            
    def cancelManualDrawing(self):
        self.current = None
        self.drawingPolygon.emit(False)
        self.update()

    def setLastLabel(self, text, flags):
        assert text
        self.shapes[-1].label = text
        self.shapes[-1].flags = flags
        self.shapesBackups.pop()
        self.storeShapes()
        return self.shapes[-1]

    def undoLastLine(self):
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.setOpen()
        if self.createMode in ["polygon", "linestrip"]:
            self.line.points = [self.current[-1], self.current[0]]
        elif self.createMode in ["rectangle", "line", "circle"]:
            self.current.points = self.current.points[0:1]
        elif self.createMode == "point":
            self.current = None
        self.drawingPolygon.emit(True)

    def undoLastPoint(self):
        if not self.current or self.current.isClosed():
            return
        self.current.popPoint()
        if len(self.current) > 0:
            self.line[0] = self.current[-1]
        else:
            self.current = None
            self.drawingPolygon.emit(False)
        self.update()

    def loadPixmap(self, pixmap, clear_shapes=True):
        self.pixmap = pixmap
        if clear_shapes:
            self.shapes = []
        self.update()

    def loadShapes(self, shapes, replace=True):
        if replace:
            self.shapes = list(shapes)
        else:
            self.shapes.extend(shapes)
        self.storeShapes()
        self.current = None
        self.hShape = None
        self.hVertex = None
        self.hEdge = None
        self.update()

    def setShapeVisible(self, shape, value):
        self.visible[shape] = value
        self.update()

    def overrideCursor(self, cursor):
        self.restoreCursor()
        self._cursor = cursor
        QtWidgets.QApplication.setOverrideCursor(cursor)

    def restoreCursor(self):
        QtWidgets.QApplication.restoreOverrideCursor()

    def resetState(self):
        self.restoreCursor()
        self.pixmap = None
        self.shapesBackups = []
        self.update()
