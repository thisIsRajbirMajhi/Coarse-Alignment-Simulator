# gui/widgets/camera_card.py - Premium camera card widget for video feeds
#
# Extracted from MainWindow._make_camera_card factory (gui/main_window.py:363ff).
# Single responsibility: create a styled camera viewport card (header + black video + hidden footer).

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout


def create_camera_card(title_text: str, res_text: str, is_primary: bool):
    """Create a premium camera card (header + video viewport + footer).

    Returns:
        tuple[QFrame, QLabel, QLabel, QLabel, QLabel, QFrame]: (
            card, vid_label, res_badge, live_badge, footer_info, footer_frame
        )
    The caller (MainWindow) keeps references to vid_label etc for pixmap updates.
    """
    card = QFrame()
    card.setObjectName("cameraCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(0, 0, 0, 0)
    card_layout.setSpacing(0)

    # Header — refined light with monochrome type hint
    card_hdr = QFrame()
    card_hdr.setObjectName("cameraCardHeader")
    card_hdr.setFixedHeight(42)
    h = QHBoxLayout(card_hdr)
    h.setContentsMargins(12, 8, 12, 8)
    h.setSpacing(8)
    title_col = QVBoxLayout()
    title_col.setSpacing(1)
    title_col.setContentsMargins(0, 0, 0, 0)
    ttl = QLabel(title_text)
    ttl.setObjectName("cameraTitle")
    title_col.addWidget(ttl)
    sub = QLabel("Monochrome Focal Plane Array" if is_primary else "Overview — World Size")
    sub.setStyleSheet("color:#6b7280; font-size:9px; background: transparent;")
    title_col.addWidget(sub)
    h.addLayout(title_col)
    h.addStretch()
    live = QLabel("LIVE")
    live.setObjectName("liveBadge")
    live.setProperty("active", False)
    card._live_badge = live  # type: ignore
    h.addWidget(live)
    # Resolution badge hidden per spec — keep for compat but not visible
    res = QLabel(res_text)
    res.setObjectName("resBadge")
    res.hide()
    card._res_badge = res  # type: ignore
    card_layout.addWidget(card_hdr)

    # Video viewport — pitch black with thin monochrome frame
    wrap = QFrame()
    wrap.setObjectName("videoFrameWrap")
    wrap.setStyleSheet("QFrame#videoFrameWrap { background: #000000; border: 1px solid #1f2937; border-radius: 4px; }")
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(1, 1, 1, 1)
    wl.setSpacing(0)
    vid = QLabel()
    vid.setObjectName("videoFeed")
    vid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    vid.setAlignment(Qt.AlignCenter)
    vid.setScaledContents(False)
    vid.setMinimumSize(260, 260)
    vid.setStyleSheet("QLabel#videoFeed { background: #000000; border: none; color: #6b7280; }")
    wl.addWidget(vid, 1)
    card_layout.addWidget(wrap, 1)

    # Footer — minimal, hidden per spec (no in-screen details)
    foot = QFrame()
    foot.setObjectName("cameraCardFooter")
    foot.setFixedHeight(22)
    fl = QHBoxLayout(foot)
    fl.setContentsMargins(10, 4, 10, 4)
    fl.setSpacing(8)
    info = QLabel("—")
    info.setStyleSheet("color:#6b7280; font-size:10px; font-family:'Consolas','Courier New',monospace; background: transparent; border: none;")
    info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    card._footer_info = info  # type: ignore
    fl.addWidget(info, 1)
    hint = QLabel("30 Hz" if is_primary else "5000 x 5000")
    hint.setStyleSheet("color:#9ca3af; font-size:9px; background: transparent;")
    fl.addWidget(hint)
    foot.hide()
    card_layout.addWidget(foot)

    return card, vid, res, live, info, foot


__all__ = ["create_camera_card"]
