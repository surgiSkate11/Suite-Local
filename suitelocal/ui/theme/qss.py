from suitelocal.ui.theme.tokens import TOKENS, DesignTokens


def build_stylesheet(tokens: DesignTokens = TOKENS) -> str:
    return f"""
    QWidget {{
        color: {tokens.text_900};
        font-family: "Inter", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QToolTip {{
        color: {tokens.text_900};
        background: {tokens.surface};
        border: 1px solid {tokens.border_strong};
        border-radius: 6px;
        padding: 6px 8px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {tokens.border_strong};
        border-radius: 5px;
        min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {tokens.text_400}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0 4px 2px 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {tokens.border_strong};
        border-radius: 5px;
        min-width: 36px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {tokens.text_400}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
        width: 0;
    }}
    QMainWindow, #centralContainer, #content, #pageContent,
    #pageScroll, #pageViewport, QStackedWidget {{
        background: {tokens.background};
        border: 0;
    }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 1px solid {tokens.border_strong};
        border-radius: {tokens.radius_control}px;
        min-height: {tokens.control_height}px;
        padding: 0 12px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 2px solid {tokens.brand_500};
        padding: 0 11px;
    }}
    QPushButton {{
        background: {tokens.brand_500};
        color: {tokens.surface};
        border: 0;
        border-radius: {tokens.radius_control}px;
        min-height: {tokens.control_height}px;
        padding: 0 16px;
        font-weight: 600;
        text-align: center;
    }}
    QPushButton::icon {{
        width: 18px;
        height: 18px;
    }}
    QPushButton:hover {{ background: {tokens.brand_600}; }}
    QPushButton:pressed {{ background: {tokens.brand_800}; }}
    QPushButton:disabled {{ background: {tokens.border}; color: {tokens.text_400}; }}
    QPushButton:focus {{
        border: 2px solid {tokens.brand_400};
        padding: 0 14px;
    }}
    QPushButton:checked {{ background: {tokens.brand_800}; }}
    #primaryAction {{
        background: {tokens.brand_500};
        min-height: {tokens.large_action_height}px;
        font-size: 15px;
        font-weight: 700;
    }}
    #secondaryAction {{
        background: {tokens.surface};
        color: {tokens.text_700};
        border: 1px solid {tokens.border_strong};
    }}
    #secondaryAction:hover {{ background: {tokens.brand_50}; }}
    #surfaceCard, #contentCard {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_card}px;
    }}
    QTableWidget {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 0;
        gridline-color: {tokens.border};
        alternate-background-color: {tokens.surface};
        selection-background-color: {tokens.brand_50};
        selection-color: {tokens.text_900};
        outline: 0;
    }}
    QTableWidget::item {{ height: 48px; padding: 0 12px; }}
    #cartTable::item, #paymentTable::item {{ height: 30px; padding: 0 10px; }}
    #cartTable, #paymentTable {{ font-size: 12px; }}
    #cartTable::item:selected, #paymentTable::item:selected {{
        background: {tokens.brand_50};
        color: {tokens.text_900};
    }}
    #cartTable QHeaderView::section, #paymentTable QHeaderView::section {{ min-height: 36px; padding: 0 10px; }}
    QTableWidget::item:hover {{ background: {tokens.brand_50}; }}
    QTableWidget QTableCornerButton::section {{
        background: {tokens.brand_100};
        border: 0;
    }}
    QHeaderView::section {{
        background: {tokens.brand_100};
        color: {tokens.text_700};
        border: 0;
        padding: 0 12px;
        min-height: 40px;
        font-weight: 600;
    }}
    QCheckBox {{
        spacing: 8px;
        color: {tokens.text_700};
        min-height: 32px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1px solid {tokens.border_strong};
        border-radius: 5px;
        background: {tokens.surface};
    }}
    QCheckBox::indicator:hover {{ border-color: {tokens.brand_500}; }}
    QCheckBox::indicator:checked {{
        background: {tokens.brand_500};
        border-color: {tokens.brand_500};
    }}
    QComboBox {{
        padding-right: 32px;
    }}
    QComboBox::drop-down {{
        width: 30px;
        border: 0;
        border-left: 1px solid {tokens.border};
    }}
    QComboBox QAbstractItemView {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 1px solid {tokens.border_strong};
        selection-background-color: {tokens.brand_50};
        selection-color: {tokens.text_900};
        padding: 4px;
    }}
    #pageTitle {{ color: {tokens.text_900}; font-size: 24px; font-weight: 700; }}
    #pageSubtitle {{ color: {tokens.text_500}; font-size: 13px; }}
    #inlineMessage {{
        color: {tokens.success};
        background: {tokens.success_background};
        border: 1px solid {tokens.success_border};
        border-radius: {tokens.radius_control}px;
        padding: 8px 10px;
    }}
    #textField[state="error"] {{
        border: 1px solid {tokens.danger};
    }}
    #kpiCard {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_card}px;
        min-height: 108px;
    }}
    #kpiLabel {{ color: {tokens.text_500}; font-size: 11px; font-weight: 600; }}
    #kpiValue {{ color: {tokens.text_900}; font-size: 28px; font-weight: 700; }}
    #kpiTrend {{ color: {tokens.text_500}; font-size: 11px; }}
    #kpiIcon {{
        background: {tokens.brand_100};
        color: {tokens.brand_500};
        border-radius: 12px;
        min-width: 40px;
        min-height: 40px;
        max-width: 40px;
        max-height: 40px;
        padding: 0;
    }}
    #statusBadge {{
        border-radius: 999px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 600;
    }}
    #statusBadge[state="success"] {{
        color: {tokens.success};
        background: {tokens.success_background};
        border: 1px solid {tokens.success_border};
    }}
    #statusBadge[state="warning"] {{
        color: {tokens.warning};
        background: {tokens.warning_background};
        border: 1px solid {tokens.warning_border};
    }}
    #statusBadge[state="danger"] {{
        color: {tokens.danger};
        background: {tokens.danger_background};
        border: 1px solid {tokens.danger_border};
    }}
    #statusBadge[state="info"] {{
        color: {tokens.info};
        background: {tokens.info_background};
        border: 1px solid {tokens.info_border};
    }}
    #emptyState {{
        background: {tokens.surface};
        border: 1px dashed {tokens.border_strong};
        border-radius: {tokens.radius_card}px;
    }}
    #emptyTitle, #dialogTitle, #drawerTitle {{
        color: {tokens.text_900};
        font-size: 17px;
        font-weight: 600;
    }}
    #emptyDescription {{ color: {tokens.text_500}; }}
    #skeleton {{ background: {tokens.border}; border-radius: {tokens.radius_control}px; }}
    #toast {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_control}px;
    }}
    #toast[state="success"] {{ border-left: 4px solid {tokens.success}; }}
    #toast[state="danger"] {{ border-left: 4px solid {tokens.danger}; }}
    #appDialog, #drawer {{ background: {tokens.surface}; border-radius: {tokens.radius_panel}px; }}
    #ghostButton {{ background: transparent; color: {tokens.text_500}; padding: 0; }}
    #sidebar {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                    stop: 0 {tokens.brand_900}, stop: 1 {tokens.brand_950});
        min-width: 248px;
        max-width: 248px;
    }}
    #brand {{ color: {tokens.surface}; font-size: 20px; font-weight: 700; padding: 18px 14px 22px; }}
    #brand small {{ color: rgba(255,255,255,0.65); font-size: 11px; font-weight: 500; }}
    #currentUser {{ color: {tokens.surface}; background: rgba(255,255,255,0.08); border-radius: 12px; padding: 12px; }}
    #currentUser span {{ color: {tokens.brand_400}; font-size: 10px; letter-spacing: 1px; }}
    #navigation {{ background: transparent; border: 0; color: rgba(255,255,255,0.82); outline: 0; }}
    #navigation::item {{ padding: 11px 14px; border-radius: 10px; margin: 3px 0; }}
    #navigation[collapsed="true"]::item {{
        padding: 11px 0;
        margin: 3px 4px;
    }}
    #navigation::item:selected {{ background: {tokens.brand_500}; color: {tokens.surface}; font-weight: 600; }}
    #navigation::item:hover:!selected {{ background: rgba(255,255,255,0.08); }}
    #navigation::item[data-role="section"] {{ color: {tokens.brand_400}; font-size: 10px; font-weight: 600; padding-top: 18px; }}
    #logoutButton {{ background: transparent; color: rgba(255,255,255,0.75); text-align: left; padding: 8px 12px; min-height: 32px; }}
    #logoutButton:hover {{ background: rgba(255,255,255,0.08); color: {tokens.surface}; }}
    #promoCard {{ background: {tokens.brand_800}; color: {tokens.surface}; border-radius: 12px; padding: 16px; font-weight: 600; }}
    #topbar {{ background: {tokens.surface}; border-bottom: 1px solid {tokens.border}; min-height: 64px; }}
    #topSearch {{ background: {tokens.background}; border: 1px solid {tokens.border}; border-radius: 10px; padding: 0 12px; }}
    #topDate {{ background: {tokens.surface}; border: 0; color: {tokens.text_700}; }}
    #topAccount {{ color: {tokens.text_900}; padding-left: 8px; }}
    #topAccount span {{ color: {tokens.text_500}; font-size: 10px; }}
    #offlineStatus {{ color: {tokens.success}; background: {tokens.success_background}; border-radius: 999px; padding: 7px 10px; font-size: 12px; font-weight: 500; }}
    #authDialog {{ background: {tokens.surface}; }}
    #authBrandPanel {{ background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 {tokens.brand_900}, stop: 1 {tokens.brand_950}); }}
    #authBrandTitle {{ color: {tokens.surface}; font-size: 30px; font-weight: 700; }}
    #authLogo {{ background: {tokens.brand_500}; color: {tokens.surface}; border-radius: 12px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; font-size: 16px; font-weight: 700; }}
    #authBrandText, #authBenefit {{ color: rgba(255,255,255,0.75); }}
    #authTitle {{ color: {tokens.text_900}; font-size: 24px; font-weight: 700; }}
    #authSubtitle, #authVersion {{ color: {tokens.text_500}; }}
    #authLabel {{ color: {tokens.text_700}; font-size: 12px; font-weight: 600; }}
    #authField {{ background: {tokens.surface}; color: {tokens.text_900}; border: 1px solid {tokens.border_strong}; border-radius: 10px; padding: 0 12px; }}
    #authField:focus {{ border: 1px solid {tokens.brand_500}; }}
    #authError {{ color: {tokens.danger}; background: {tokens.danger_background}; border: 1px solid {tokens.danger_border}; border-radius: 10px; padding: 10px; }}
    #authButton {{ min-height: 44px; font-size: 14px; }}
    #dashboardIntro, #contentCard {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: {tokens.radius_card}px; }}
    #introTitle {{ color: {tokens.text_900}; font-size: 16px; font-weight: 700; }}
    #introHint {{ color: {tokens.text_500}; }}
    #sectionTitle {{ color: {tokens.text_900}; font-size: 17px; font-weight: 600; }}
    #resultCount {{ color: {tokens.text_500}; font-size: 12px; }}
    #dashboardSummary {{ color: {tokens.text_700}; background: {tokens.brand_50}; border-radius: {tokens.radius_control}px; padding: 16px; line-height: 1.5; }}
    #cartCount {{ color: {tokens.text_500}; font-size: 11px; }}
    #metricCard {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: {tokens.radius_card}px; min-height: 108px; }}
    #metricCard[accent="blue"] {{ border-top: 3px solid {tokens.brand_500}; }}
    #metricCard[accent="green"] {{ border-top: 3px solid {tokens.success}; }}
    #metricCard[accent="orange"] {{ border-top: 3px solid {tokens.warning}; }}
    #metricCard[accent="purple"] {{ border-top: 3px solid #6D44D9; }}
    #metricIcon {{ background: {tokens.brand_100}; color: {tokens.brand_500}; border-radius: 8px; padding: 5px 7px; font-size: 10px; font-weight: 700; }}
    #metricLabel {{ color: {tokens.text_500}; font-size: 10px; font-weight: 600; letter-spacing: .5px; }}
    #metricValue {{ color: {tokens.text_900}; font-size: 26px; font-weight: 700; }}
    #metricTrend {{ color: {tokens.text_500}; font-size: 11px; }}
    #periodButton, #secondaryAction {{ background: {tokens.surface}; color: {tokens.text_700}; border: 1px solid {tokens.border_strong}; border-radius: {tokens.radius_control}px; }}
    #checkoutSummary {{ background: {tokens.brand_100}; border-radius: {tokens.radius_control}px; padding: 10px 12px; }}
    #checkoutSummary QLabel {{ color: {tokens.text_500}; font-size: 11px; font-weight: 600; }}
    #checkoutSummary #totalLabel {{ color: {tokens.text_900}; font-size: 25px; font-weight: 700; }}
    #checkoutDetail {{ color: {tokens.text_500}; font-size: 11px; }}
    #paymentStatus {{ border-radius: {tokens.radius_control}px; padding: 8px 10px; font-size: 12px; }}
    #paymentStatus[state="info"] {{ color: {tokens.info}; background: {tokens.info_background}; }}
    #paymentStatus[state="warning"] {{ color: {tokens.warning}; background: {tokens.warning_background}; }}
    #paymentStatus[state="success"] {{ color: {tokens.success}; background: {tokens.success_background}; }}
    #productResults {{
        background: {tokens.surface};
        border: 0;
        color: {tokens.text_700};
        outline: 0;
    }}
    #productResults::item {{
        padding: 12px;
        min-height: 48px;
        border-bottom: 1px solid {tokens.border};
        border-radius: {tokens.radius_control}px;
    }}
    #productResults::item:selected {{
        background: {tokens.brand_50};
        color: {tokens.brand_500};
        border-left: 3px solid {tokens.brand_500};
    }}
    #scannerStatus {{ color: {tokens.text_500}; font-size: 11px; padding: 2px 4px; }}
    #scannerStatus[state="success"] {{ color: {tokens.success}; }}
    #scannerStatus[state="error"] {{ color: {tokens.danger}; }}
    #paymentSummary {{
        color: {tokens.text_500};
        background: {tokens.brand_50};
        border-radius: {tokens.radius_control}px;
        padding: 8px 10px;
    }}
    #drawer {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        padding: 4px;
    }}
    #drawerTitle {{ color: {tokens.text_900}; font-size: 17px; font-weight: 600; }}
    """
