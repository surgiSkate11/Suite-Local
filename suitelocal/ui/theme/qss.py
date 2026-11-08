from suitelocal.ui.theme.icons import icon_file
from suitelocal.ui.theme.tokens import LIGHT_TOKENS, DesignTokens


def build_stylesheet(tokens: DesignTokens = LIGHT_TOKENS) -> str:
    check_mark = icon_file("check", tokens.on_brand, 18, stroke_width=2.5).as_posix()
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
        border: 1px solid {tokens.border_input};
        border-radius: {tokens.radius_control}px;
        min-height: {tokens.control_height}px;
        padding: 0 12px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 2px solid {tokens.focus};
        padding: 0 11px;
    }}
    QPushButton {{
        background: {tokens.brand_500};
        color: {tokens.on_brand};
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
    QPushButton:pressed {{ background: {tokens.brand_600}; }}
    QPushButton:disabled {{ background: {tokens.border}; color: {tokens.text_400}; }}
    QPushButton:focus {{
        border: 2px solid {tokens.focus_ring};
        padding: 0 14px;
    }}
    QPushButton:checked {{ background: {tokens.brand_800}; }}
    #primaryAction {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                    stop: 0 {tokens.brand_600}, stop: 1 {tokens.brand_500});
        min-height: {tokens.large_action_height}px;
        font-size: 15px;
        font-weight: 700;
    }}
    #primaryAction:hover {{ background: {tokens.brand_600}; }}
    #primaryAction:pressed {{ background: {tokens.brand_500}; }}
    #primaryAction:disabled {{ background: {tokens.border}; color: {tokens.text_400}; }}
    #primaryAction[size="hero"] {{
        min-height: 60px;
        border-radius: {tokens.radius_panel}px;
        font-size: 17px;
    }}
    #secondaryAction {{
        background: {tokens.surface};
        color: {tokens.text_700};
        border: 1px solid {tokens.border_strong};
    }}
    #secondaryAction:hover {{ background: {tokens.brand_50}; }}
    QPushButton[variant="secondary"] {{
        background: {tokens.surface};
        color: {tokens.text_700};
        border: 1px solid {tokens.border_input};
    }}
    QPushButton[variant="secondary"]:hover {{ background: {tokens.brand_50}; }}
    QPushButton[variant="danger"] {{ background: {tokens.danger}; color: {tokens.on_danger}; }}
    QPushButton[variant="danger"]:hover {{ background: {tokens.text_900}; }}
    QPushButton[variant="ghost"] {{ background: transparent; color: {tokens.text_700}; }}
    QPushButton[variant="ghost"]:hover {{ background: {tokens.sunken}; }}
    QPushButton[variant="champagne"] {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                    stop: 0 {tokens.champagne_100}, stop: 1 {tokens.champagne_500});
        color: {tokens.on_champagne};
        border-radius: {tokens.radius_card}px;
        min-height: 58px;
        font-size: 17px;
        font-weight: 700;
    }}
    QPushButton[variant="champagne"]:hover {{ background: {tokens.champagne_100}; }}
    QPushButton[variant="champagne"]:pressed {{ background: {tokens.champagne_500}; }}
    QPushButton[variant="champagne"]:disabled {{ background: {tokens.border}; color: {tokens.text_400}; }}
    #segmented {{
        background: {tokens.sunken};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_pad}px;
    }}
    #segmented QPushButton[variant="segment"] {{
        background: transparent;
        color: {tokens.text_700};
        border: 0;
        border-radius: 10px;
        min-height: 32px;
        padding: 0 14px;
        font-size: 13px;
        font-weight: 400;
    }}
    #segmented QPushButton[variant="segment"]:hover {{ background: {tokens.brand_50}; }}
    #segmented QPushButton[variant="segment"]:checked {{
        background: {tokens.surface};
        color: {tokens.text_900};
        font-weight: 600;
    }}
    #segmented QPushButton[variant="segment"]:focus {{
        border: 2px solid {tokens.focus};
        padding: 0 12px;
    }}
    QLabel[role="display"], #pageTitle {{
        color: {tokens.text_900};
        font-family: {tokens.font_serif};
        font-size: 28px;
        font-weight: 400;
    }}
    QLabel[role="eyebrow"] {{ color: {tokens.text_500}; font-size: 12px; }}
    QLabel[role="kbd"] {{
        color: {tokens.text_700};
        background: {tokens.sunken};
        border: 1px solid {tokens.border_strong};
        border-bottom-width: 2px;
        border-radius: 6px;
        padding: 1px 7px;
        font-size: 11px;
    }}
    #ticketPanel {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_ticket}px;
    }}
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
        background: {tokens.sunken};
        border: 0;
    }}
    QHeaderView::section {{
        background: {tokens.sunken};
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
        border: 1px solid {tokens.border_input};
        border-radius: 5px;
        background: {tokens.surface};
    }}
    QCheckBox::indicator:hover {{ border-color: {tokens.brand_500}; }}
    QCheckBox::indicator:focus {{ border-color: {tokens.focus}; }}
    QCheckBox::indicator:checked {{
        background: {tokens.brand_500};
        border-color: {tokens.brand_500};
        image: url({check_mark});
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
    #pageSubtitle {{ color: {tokens.text_500}; font-size: 13px; }}
    #moduleHint {{ color: {tokens.text_500}; font-size: 12px; padding-left: 26px; }}
    #categoryList {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_control}px;
        padding: 4px;
        outline: 0;
    }}
    #categoryList::item {{ padding: 8px 10px; border-radius: 8px; }}
    #categoryList::item:hover {{ background: {tokens.brand_50}; }}
    #categoryList::item:selected {{ background: {tokens.brand_100}; color: {tokens.text_900}; }}
    #inlineMessage {{
        color: {tokens.success};
        background: {tokens.success_background};
        border: 1px solid {tokens.success_border};
        border-radius: {tokens.radius_control}px;
        padding: 8px 10px;
    }}
    #inlineMessage[state="warning"] {{
        color: {tokens.warning};
        background: {tokens.warning_background};
        border: 1px solid {tokens.warning_border};
    }}
    #inlineMessage[state="error"] {{
        color: {tokens.danger};
        background: {tokens.danger_background};
        border: 1px solid {tokens.danger_border};
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
    #toast[state="info"] {{ border-left: 4px solid {tokens.info}; }}
    #toast[state="warning"] {{ border-left: 4px solid {tokens.warning}; }}
    #toastText {{ color: {tokens.text_900}; }}
    #toastClose {{ background: transparent; border-radius: 14px; min-height: 0; padding: 0; }}
    #toastClose:hover {{ background: {tokens.background}; }}
    #drawerClose {{ background: transparent; border-radius: 20px; min-height: 0; padding: 0; }}
    #drawerClose:hover {{ background: {tokens.background}; }}
    #dangerAction {{ background: {tokens.danger}; color: {tokens.on_danger}; }}
    #appDialog, #drawer {{ background: {tokens.surface}; border-radius: {tokens.radius_panel}px; }}
    #ghostButton {{ background: transparent; color: {tokens.text_500}; padding: 0; }}
    #sidebar {{ background: {tokens.rail}; }}
    #brandMark {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                    stop: 0 {tokens.champagne_300}, stop: 1 {tokens.champagne_700});
        color: {tokens.on_champagne};
        border-radius: 11px;
        min-width: 36px;
        max-width: 36px;
        min-height: 36px;
        max-height: 36px;
        font-size: 15px;
        font-weight: 800;
    }}
    #brandName {{ color: {tokens.rail_strong}; font-size: 15px; font-weight: 700; }}
    #brandBusiness {{ color: {tokens.rail_text}; font-size: 12px; }}
    #navigation {{ background: transparent; border: 0; color: {tokens.rail_text}; outline: 0; }}
    #navigation::item {{
        padding: 10px 12px;
        border-radius: 10px;
        margin: 2px 0;
        border-left: 2px solid transparent;
    }}
    #navigation[collapsed="true"]::item {{ padding: 10px 0; margin: 2px 4px; }}
    #navigation::item:selected {{
        background: {tokens.rail_active};
        color: {tokens.rail_strong};
        border-left: 2px solid {tokens.champagne_300};
        font-weight: 600;
    }}
    #navigation::item:hover:!selected {{ background: {tokens.rail_hover}; color: {tokens.rail_strong}; }}
    #navigation::item:disabled {{ color: {tokens.rail_group}; background: transparent; }}
    #registerCard {{
        background: {tokens.rail_card};
        border: 1px solid {tokens.rail_border};
        border-radius: 16px;
    }}
    #registerLabel, #userRole {{ color: {tokens.rail_text}; font-size: 12px; }}
    #registerStatus {{ color: {tokens.rail_text}; font-size: 12px; font-weight: 600; }}
    #registerStatus[state="open"] {{ color: {tokens.rail_live}; }}
    #registerValue {{ color: {tokens.rail_strong}; font-size: 12px; font-weight: 600; }}
    #registerDivider {{ background: {tokens.rail_border}; max-height: 1px; min-height: 1px; border: 0; }}
    #avatar {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                    stop: 0 {tokens.champagne_300}, stop: 1 {tokens.champagne_700});
        color: {tokens.on_champagne};
        border-radius: 16px;
        min-width: 32px;
        max-width: 32px;
        min-height: 32px;
        max-height: 32px;
        font-size: 12px;
        font-weight: 700;
    }}
    #userName {{ color: {tokens.rail_strong}; font-size: 13px; font-weight: 600; }}
    #logoutButton {{
        background: transparent;
        color: {tokens.rail_text};
        border-radius: 10px;
        text-align: left;
        padding: 0 12px;
        min-height: 36px;
        font-weight: 500;
    }}
    #logoutButton:hover {{ background: {tokens.rail_hover}; color: {tokens.rail_strong}; }}
    #logoutButton[collapsed="true"] {{ padding: 0; text-align: center; }}
    #promoCard {{ background: {tokens.brand_800}; color: {tokens.on_brand}; border-radius: 12px; padding: 16px; font-weight: 600; }}
    #topbar {{ background: {tokens.background}; border: 0; min-height: 64px; }}
    #topSearch {{
        background: {tokens.surface};
        border: 1px solid {tokens.border_strong};
        border-radius: {tokens.radius_control}px;
        padding: 0 12px;
        min-height: 40px;
    }}
    #topDate {{ background: transparent; border: 0; color: {tokens.text_500}; font-size: 12px; }}
    #topAccount {{ background: transparent; color: {tokens.text_900}; padding-left: 8px; }}
    #themeToggle {{
        background: {tokens.surface};
        color: {tokens.text_700};
        border: 1px solid {tokens.border_strong};
        border-radius: {tokens.radius_control}px;
        min-height: 38px;
        padding: 0 14px;
        font-size: 13px;
    }}
    #themeToggle:hover {{ background: {tokens.brand_50}; }}
    #themeToggle:checked {{ background: {tokens.sunken}; color: {tokens.text_900}; }}
    #themeToggle:focus {{ border: 2px solid {tokens.focus}; padding: 0 13px; }}
    #statusBar {{ background: {tokens.surface}; border-top: 1px solid {tokens.border}; }}
    #statusBar QLabel {{ background: transparent; color: {tokens.text_500}; font-size: 12px; }}
    #statusBar #statusValue {{ color: {tokens.text_700}; font-weight: 600; }}
    #statusDot {{ color: {tokens.text_400}; font-size: 10px; }}
    #statusDot[state="ok"] {{ color: {tokens.success}; }}
    #statusDot[state="warn"] {{ color: {tokens.warning}; }}
    #offlineStatus {{ color: {tokens.success}; background: {tokens.success_background}; border-radius: 999px; padding: 7px 10px; font-size: 12px; font-weight: 500; }}
    #authDialog {{ background: {tokens.surface}; }}
    #authBrandPanel {{ background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 {tokens.hero_2}, stop: 1 {tokens.rail}); }}
    #authBrandTitle {{ color: {tokens.hero_text}; font-family: {tokens.font_serif}; font-size: 30px; font-weight: 400; }}
    #authLogo {{ background: {tokens.champagne_300}; color: {tokens.on_champagne}; border-radius: 12px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; font-size: 16px; font-weight: 700; }}
    #authBrandText, #authBenefit {{ color: {tokens.hero_muted}; }}
    #authTitle {{ color: {tokens.text_900}; font-family: {tokens.font_serif}; font-size: 26px; font-weight: 400; }}
    #authSubtitle, #authVersion {{ color: {tokens.text_500}; }}
    #authLabel {{ color: {tokens.text_700}; font-size: 12px; font-weight: 600; }}
    #authField {{ background: {tokens.surface}; color: {tokens.text_900}; border: 1px solid {tokens.border_input}; border-radius: 10px; padding: 0 12px; }}
    #authField:focus {{ border: 1px solid {tokens.focus}; }}
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
    #metricCard[accent="purple"] {{ border-top: 3px solid {tokens.accent_purple}; }}
    #metricIcon {{ background: {tokens.brand_100}; color: {tokens.brand_500}; border-radius: 8px; padding: 5px 7px; font-size: 10px; font-weight: 700; }}
    #metricLabel {{ color: {tokens.text_500}; font-size: 10px; font-weight: 600; letter-spacing: .5px; }}
    #metricValue {{ color: {tokens.text_900}; font-size: 26px; font-weight: 700; }}
    #metricTrend {{ color: {tokens.text_500}; font-size: 11px; }}
    #periodButton, #secondaryAction {{ background: {tokens.surface}; color: {tokens.text_700}; border: 1px solid {tokens.border_strong}; border-radius: {tokens.radius_control}px; }}
    #checkoutSummary {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                    stop: 0 {tokens.hero_2}, stop: 1 {tokens.hero});
        border-radius: {tokens.radius_panel}px;
    }}
    #checkoutSummary QLabel {{ color: {tokens.hero_muted}; font-size: 12px; background: transparent; }}
    #checkoutSummary #checkoutCaption {{ font-weight: 600; }}
    #checkoutSummary #totalLabel {{ color: {tokens.hero_text}; font-size: 40px; font-weight: 300; }}
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
    #productResults::item {{ border: 0; padding: 0; }}
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
    #paymentScrim {{ background: rgba(20,23,31,0.42); }}
    #paymentCard {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_dialog}px;
    }}
    #paymentLeft {{ background: transparent; }}
    #paymentRight {{
        background: {tokens.mist};
        border: 0;
        border-left: 1px solid {tokens.border};
        border-top-right-radius: {tokens.radius_dialog}px;
        border-bottom-right-radius: {tokens.radius_dialog}px;
    }}
    #paymentRight QWidget {{ background: transparent; }}
    #paymentEyebrow {{ color: {tokens.text_500}; font-size: 12px; }}
    #paymentTitle {{
        color: {tokens.text_900};
        font-family: {tokens.font_serif};
        font-size: 30px;
        font-weight: 400;
    }}
    #paymentClose {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_control}px;
        min-height: 0;
        padding: 0;
    }}
    #paymentClose:hover {{ background: {tokens.background}; }}
    #paymentDue {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                    stop: 0 {tokens.hero_2}, stop: 1 {tokens.hero});
        border-radius: {tokens.radius_panel}px;
    }}
    #paymentDue QLabel {{ background: transparent; }}
    #paymentDueTitle {{ color: {tokens.hero_muted}; font-size: 13px; }}
    #paymentDueNote {{ color: {tokens.hero_muted}; font-size: 12px; }}
    #paymentDueAmount {{ color: {tokens.hero_text}; font-size: 48px; font-weight: 300; }}
    #paymentSectionLabel {{ color: {tokens.text_500}; font-size: 13px; font-weight: 600; }}
    #paymentRows, #paymentScroll, #paymentScroll > QWidget > QWidget {{ background: transparent; }}
    #paymentRow {{
        background: {tokens.mist};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_card}px;
    }}
    #paymentRow[active="true"] {{
        background: {tokens.surface};
        border: 2px solid {tokens.brand_800};
    }}
    #paymentRow QLabel {{ background: transparent; }}
    #paymentIcon {{ border-radius: {tokens.radius_control}px; background: {tokens.brand_100}; }}
    #paymentIcon[method="cash"] {{ background: {tokens.champagne_background}; }}
    #paymentIcon[method="card"] {{ background: {tokens.success_background}; }}
    #paymentRowTitle {{ color: {tokens.text_900}; font-size: 15px; font-weight: 600; }}
    #paymentRowSubtitle {{ color: {tokens.text_500}; font-size: 12px; }}
    #paymentRowAmount {{ color: {tokens.text_900}; font-size: 20px; font-weight: 600; }}
    #paymentState {{ border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; }}
    #paymentState[state="received"] {{ color: {tokens.success}; background: {tokens.success_background}; }}
    #paymentState[state="pending"] {{ color: {tokens.champagne_text}; background: {tokens.champagne_background}; }}
    #paymentRemove {{ background: transparent; border-radius: 14px; min-height: 0; padding: 0; }}
    #paymentRemove:hover {{ background: {tokens.background}; }}
    #paymentForm {{
        background: {tokens.mist};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_card}px;
    }}
    #paymentForm QLineEdit, #paymentForm QComboBox {{ background: {tokens.surface}; }}
    #addPayment {{
        background: transparent;
        color: {tokens.text_700};
        border: 1px dashed {tokens.border_input};
        border-radius: {tokens.radius_pad}px;
        min-height: 48px;
    }}
    #addPayment:hover {{ background: {tokens.mist}; }}
    #paymentFieldLabel {{ color: {tokens.text_500}; font-size: 13px; font-weight: 600; }}
    #cashDisplay {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 2px solid {tokens.brand_800};
        border-radius: 18px;
        padding: 0 20px;
        font-size: 38px;
        font-weight: 300;
    }}
    #cashDisplay:disabled {{ border-color: {tokens.border_strong}; color: {tokens.text_400}; }}
    #billButton, #padButton {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_control}px;
        min-height: 44px;
        padding: 0;
        font-size: 13px;
        font-weight: 600;
    }}
    #billButton {{ color: {tokens.text_700}; }}
    #billButton[selected="true"] {{
        background: {tokens.champagne_background};
        border-color: {tokens.champagne_border};
        color: {tokens.champagne_text};
    }}
    #padButton {{ min-height: 46px; border-radius: {tokens.radius_pad}px; font-size: 20px; font-weight: 400; }}
    #billButton:hover, #padButton:hover {{ background: {tokens.background}; }}
    #billButton:pressed, #padButton:pressed {{ background: {tokens.border}; }}
    #billButton:disabled, #padButton:disabled {{ color: {tokens.text_400}; background: {tokens.mist}; }}
    #billButton:focus, #padButton:focus {{ border: 2px solid {tokens.brand_800}; padding: 0; }}
    #changeBox {{
        background: {tokens.success_background};
        border: 1px solid {tokens.success_border};
        border-radius: {tokens.radius_card}px;
    }}
    #changeLabel {{ color: {tokens.success}; font-size: 13px; font-weight: 700; }}
    #changeValue {{ color: {tokens.success_strong}; font-size: 30px; font-weight: 600; }}
    #posHeader QLabel[role="display"] {{ font-size: 28px; }}
    #kpiTile {{
        background: {tokens.surface};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_pad}px;
    }}
    #kpiTile QLabel {{ background: transparent; }}
    #kpiTileLabel {{ color: {tokens.text_500}; font-size: 11px; }}
    #kpiTileValue {{ color: {tokens.text_900}; font-size: 16px; font-weight: 600; }}
    #scanBar {{
        background: {tokens.surface};
        border: 2px solid {tokens.brand_500};
        border-radius: 16px;
    }}
    #scanBar QLabel {{ background: transparent; }}
    #scanInput {{
        background: transparent;
        border: 0;
        padding: 0;
        min-height: 0;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 19px;
    }}
    #scanInput:focus {{ border: 0; padding: 0; }}
    #scanInput[empty="true"] {{ font-family: "Inter", "Segoe UI", sans-serif; font-size: 16px; }}
    #scanHint {{
        color: {tokens.text_500};
        font-size: 12px;
        border-left: 1px solid {tokens.border};
        padding-left: 14px;
    }}
    #readerStatus {{
        color: {tokens.success};
        background: {tokens.success_background};
        border-radius: 12px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#quickKey {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 1px solid {tokens.border};
        border-radius: 12px;
        min-height: 52px;
        max-height: 52px;
        padding: 0;
        text-align: left;
    }}
    QPushButton#quickKey:hover {{ border-color: {tokens.border_strong}; background: {tokens.mist}; }}
    QPushButton#quickKey:focus {{ border: 1px solid {tokens.focus}; padding: 0; }}
    QPushButton#quickKey:disabled {{ background: {tokens.mist}; }}
    #quickKey QLabel {{ background: transparent; }}
    #quickName {{ font-size: 13px; font-weight: 600; }}
    #quickPrice {{ color: {tokens.text_500}; font-size: 11px; }}
    #quickKey:disabled #quickName, #quickKey:disabled #quickPrice {{ color: {tokens.text_400}; }}
    #productGrid, #productGridViewport, #productGridHost {{ background: transparent; border: 0; }}
    #productOverflow {{ color: {tokens.text_500}; font-size: 12px; }}
    QPushButton#productCard {{
        background: {tokens.surface};
        color: {tokens.text_900};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_card}px;
        /* QSS min/max-height override setFixedHeight(); keep in sync with ProductCard.HEIGHT. */
        min-height: 176px;
        max-height: 176px;
        padding: 0;
        text-align: left;
    }}
    QPushButton#productCard:hover {{ border-color: {tokens.border_strong}; }}
    QPushButton#productCard[current="true"] {{ background: {tokens.mist}; border-color: {tokens.border_strong}; }}
    QPushButton#productCard[inCart="true"] {{ border: 1px solid {tokens.brand_500}; }}
    QPushButton#productCard:focus {{ border: 1px solid {tokens.focus}; padding: 0; }}
    #productCard QLabel {{ background: transparent; }}
    #productName {{ font-size: 13px; font-weight: 600; }}
    #productMeta {{ color: {tokens.text_500}; font-size: 12px; }}
    #productPrice {{ font-size: 16px; font-weight: 700; }}
    #productBadge {{
        background: {tokens.sunken};
        color: {tokens.brand_500};
        border-radius: 9px;
        font-weight: 700;
    }}
    #productBadge[inCart="true"] {{ background: {tokens.brand_500}; color: {tokens.on_brand}; }}
    #productTag {{
        border-radius: 10px;
        padding: 3px 9px;
        font-size: 11px;
        font-weight: 700;
        color: {tokens.warning};
        background: {tokens.warning_background};
    }}
    #productTag[state="out"] {{ color: {tokens.danger}; background: {tokens.danger_background}; }}
    QLabel#productArt {{
        color: {tokens.art_ink};
        border-radius: 12px;
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel#productArt[size="thumb"] {{ border-radius: 10px; font-size: 12px; }}
    QLabel#productArt[tint="1"] {{ background: {tokens.art_1}; }}
    QLabel#productArt[tint="2"] {{ background: {tokens.art_2}; }}
    QLabel#productArt[tint="3"] {{ background: {tokens.art_3}; }}
    QLabel#productArt[tint="4"] {{ background: {tokens.art_4}; }}
    QLabel#productArt[tint="5"] {{ background: {tokens.art_5}; }}
    #saleTitle {{ font-size: 21px; }}
    #customerLabel, #ticketEmpty {{ color: {tokens.text_500}; font-size: 12px; }}
    #ticketLines, #ticketLinesViewport, #ticketLinesHost {{ background: transparent; border: 0; }}
    #ticketLine {{
        background: transparent;
        border: 0;
        border-bottom: 1px solid {tokens.border};
        border-left: 2px solid transparent;
    }}
    #ticketLine[highlighted="true"] {{
        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                    stop: 0 {tokens.brand_100}, stop: 1 {tokens.surface});
        border-left: 2px solid {tokens.brand_500};
    }}
    #ticketLine QLabel {{ background: transparent; }}
    #lineName {{ font-size: 13px; font-weight: 600; }}
    #lineTotal {{ font-size: 14px; font-weight: 700; }}
    #lineSub {{ color: {tokens.text_500}; font-size: 12px; }}
    #stepper {{ background: {tokens.sunken}; border: 0; border-radius: 8px; }}
    QPushButton#stepButton {{
        background: transparent;
        color: {tokens.text_700};
        border: 0;
        border-radius: 6px;
        min-height: 0;
        padding: 0;
        font-size: 15px;
    }}
    QPushButton#stepButton:hover {{ background: {tokens.surface}; }}
    #stepQty {{ font-size: 12px; font-weight: 700; background: transparent; }}
    #heroCaption {{ font-size: 11px; font-weight: 600; }}
    #recvBox {{
        background: {tokens.mist};
        border: 1px solid {tokens.border_strong};
        border-radius: {tokens.radius_pad}px;
    }}
    #recvBox QLabel {{ background: transparent; }}
    #recvCaption {{ color: {tokens.text_500}; font-size: 11px; font-weight: 600; }}
    #recvInput {{
        background: transparent;
        border: 0;
        padding: 0;
        min-height: 0;
        font-size: 20px;
        font-weight: 500;
    }}
    #recvInput:focus {{ border: 0; padding: 0; }}
    #inlineChange {{
        background: {tokens.success_background};
        border: 1px solid {tokens.success_border};
        border-radius: {tokens.radius_pad}px;
    }}
    #inlineChange QLabel {{ background: transparent; }}
    #inlineChangeCaption {{ color: {tokens.success}; font-size: 11px; font-weight: 600; }}
    #inlineChangeValue {{ color: {tokens.success_strong}; font-size: 20px; font-weight: 700; }}
    QPushButton#billChip {{
        background: {tokens.surface};
        color: {tokens.text_700};
        border: 1px solid {tokens.border};
        border-radius: 10px;
        min-height: 34px;
        max-height: 34px;
        padding: 0;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#billChip:hover {{ background: {tokens.mist}; }}
    QPushButton#billChip[selected="true"] {{
        border-color: {tokens.brand_500};
        color: {tokens.brand_500};
        background: {tokens.brand_100};
    }}
    QPushButton#billChip:focus {{ border: 1px solid {tokens.focus}; padding: 0; }}
    #referenceEdit {{ min-height: 40px; }}
    #ticketPanel #inlineMessage {{ font-size: 12px; padding: 6px 10px; }}
    QPushButton#chargeButton {{ text-align: left; padding: 0 20px; }}
    QPushButton#chargeButton:focus {{ padding: 0 18px; border: 2px solid {tokens.focus}; }}
    #chargeButton QLabel {{ background: transparent; color: {tokens.on_champagne}; font-size: 17px; font-weight: 700; }}
    #chargeButton QLabel[role="kbd"] {{
        background: rgba(26,20,7,0.08);
        border: 1px solid rgba(26,20,7,0.2);
        border-bottom-width: 2px;
        color: {tokens.on_champagne};
        font-size: 11px;
        font-weight: 400;
    }}
    #chargeButton:disabled QLabel {{ color: {tokens.text_400}; }}
    QPushButton#splitButton {{ min-height: 36px; font-size: 12px; font-weight: 500; }}
    #splitButton QLabel {{ background: transparent; }}
    """
