extends Control

const SCREEN_SIZE := Vector2i(640, 480)
const PAPER := Color(0.98, 0.99, 0.97)
const INK := Color(0.02, 0.025, 0.03)
const MUTED := Color(0.28, 0.32, 0.34)
const GUIDE := Color(0.74, 0.84, 0.92)
const OSD_BG := Color(0.04, 0.05, 0.06, 0.80)
const OSD_INK := Color(0.93, 0.96, 0.96)

const FONTS_640X240 := {
	"k64f": "res://game/640x240/k64-640x240-k64f-16px-x2w.fnt",
	"j": "res://game/640x240/k64-640x240-j-shinonome-mincho-16px-or12.ttf",
	"ck": "res://game/640x240/k64-640x240-ck-unifont-16px-or12.ttf",
	"thai": "res://game/640x240/k64-640x240-thai-pixel-12w-or12-y2x-prop-x2w.ttf",
	"arabic": "res://game/640x240/k64-640x240-arabic-sans-medium-pixel-20px-thin-y1.ttf",
}

const FONTS_320X240 := {
	"k64f": "res://game/320x240/k64-320-k64f-visual16-12px.fnt",
	"j": "res://game/320x240/k64-320-j-shinonome-mincho-12px.ttf",
	"ck": "res://game/320x240/k64-320-ck-unifont-12px.ttf",
	"thai": "res://game/320x240/k64-320-thai-light-12px-mark16-max2.ttf",
	"arabic": "res://game/320x240/k64-320-arabic-light-12px.ttf",
}

const FONTS_640X480 := {
	"k64f": "res://game/640x480/k64-640x480-k64f-16px.fnt",
	"j": "res://game/640x480/k64-640x480-j-shinonome-mincho-16px.ttf",
	"ck": "res://game/640x480/k64-640x480-ck-unifont-16px.ttf",
	"thai": "res://game/640x480/k64-640x480-thai-light-16px.ttf",
	"arabic": "res://game/640x480/k64-640x480-arabic-light-16px.ttf",
}

const MODES := [
	{
		"id": "640x240",
		"title": "640x240 surface -> 640x480 display",
		"surface_size": Vector2i(640, 240),
		"fonts": FONTS_640X240,
		"sizes": {"k64f": 16, "j": 16, "ck": 16, "thai": 16, "arabic": 20},
		"layout": "wide240",
	},
	{
		"id": "320x240",
		"title": "320x240 surface -> 640x480 display",
		"surface_size": Vector2i(320, 240),
		"fonts": FONTS_320X240,
		"sizes": {"k64f": 12, "j": 12, "ck": 12, "thai": 12, "arabic": 12},
		"layout": "small240",
	},
	{
		"id": "640x480",
		"title": "640x480 surface -> 640x480 display",
		"surface_size": Vector2i(640, 480),
		"fonts": FONTS_640X480,
		"sizes": {"k64f": 16, "j": 16, "ck": 16, "thai": 16, "arabic": 16},
		"layout": "wide480",
	},
]

var _font_cache := {}
var _mode_index := 0
var _mode_buttons: Array[Button] = []
var _surface := SubViewport.new()
var _surface_root := Control.new()
var _screen := TextureRect.new()
var _mode_label := Label.new()


func _ready() -> void:
	custom_minimum_size = Vector2(SCREEN_SIZE)
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	RenderingServer.set_default_clear_color(Color.BLACK)
	_build_screen()
	_build_mode_bar()
	set_mode(0)


func _unhandled_key_input(event: InputEvent) -> void:
	if not event.pressed:
		return
	if event.keycode == KEY_1:
		set_mode(0)
	elif event.keycode == KEY_2:
		set_mode(1)
	elif event.keycode == KEY_3:
		set_mode(2)


func _build_screen() -> void:
	_surface.disable_3d = true
	_surface.transparent_bg = false
	_surface.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(_surface)

	_surface_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_surface.add_child(_surface_root)

	_screen.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_screen.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_screen.stretch_mode = TextureRect.STRETCH_SCALE
	_screen.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_screen.texture = _surface.get_texture()
	add_child(_screen)


func _build_mode_bar() -> void:
	var panel := PanelContainer.new()
	panel.position = Vector2(8, 438)
	panel.custom_minimum_size = Vector2(624, 34)
	panel.add_theme_stylebox_override("panel", make_osd_style())
	add_child(panel)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	panel.add_child(row)

	for index in range(MODES.size()):
		var mode: Dictionary = MODES[index]
		var button := Button.new()
		button.text = "%d  %s" % [index + 1, mode["id"]]
		button.toggle_mode = true
		button.focus_mode = Control.FOCUS_NONE
		button.pressed.connect(set_mode.bind(index))
		row.add_child(button)
		_mode_buttons.append(button)

	_mode_label.text = ""
	_mode_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_mode_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_mode_label.add_theme_color_override("font_color", OSD_INK)
	_mode_label.add_theme_font_size_override("font_size", 12)
	row.add_child(_mode_label)


func set_mode(index: int) -> void:
	_mode_index = clampi(index, 0, MODES.size() - 1)
	var mode: Dictionary = MODES[_mode_index]
	var surface_size: Vector2i = mode["surface_size"]
	_surface.size = surface_size
	_surface_root.position = Vector2.ZERO
	_surface_root.size = Vector2(surface_size)
	_surface_root.custom_minimum_size = Vector2(surface_size)

	for child in _surface_root.get_children():
		_surface_root.remove_child(child)
		child.queue_free()

	for button_index in range(_mode_buttons.size()):
		_mode_buttons[button_index].button_pressed = button_index == _mode_index

	_mode_label.text = "%s  /  surface %dx%d  /  display 640x480" % [
		mode["title"],
		surface_size.x,
		surface_size.y,
	]

	draw_mode(mode)


func draw_mode(mode: Dictionary) -> void:
	var surface_size: Vector2i = mode["surface_size"]
	var bg := ColorRect.new()
	bg.color = PAPER
	bg.position = Vector2.ZERO
	bg.size = Vector2(surface_size)
	_surface_root.add_child(bg)

	match String(mode["layout"]):
		"wide240":
			draw_wide_240(mode)
		"small240":
			draw_small_240(mode)
		_:
			draw_wide_480(mode)


func draw_wide_240(mode: Dictionary) -> void:
	var fonts: Dictionary = mode["fonts"]
	var sizes: Dictionary = mode["sizes"]
	add_rule(18, 42, 604)
	add_rule(18, 116, 604)
	add_label(mode["title"], fonts["k64f"], sizes["k64f"], Vector2(18, 10), Vector2(604, 18), INK)
	add_label("K64F   HP 0123 / MENU / SCORE", fonts["k64f"], sizes["k64f"], Vector2(18, 52), Vector2(604, 20), INK)
	add_label("J      こんにちは世界 0123", fonts["j"], sizes["j"], Vector2(18, 78), Vector2(604, 20), INK)
	add_label("CK     ! ！ 漢字 龍龜 你好 안녕", fonts["ck"], sizes["ck"], Vector2(18, 104), Vector2(604, 20), INK)
	add_label("TH     กี้ กํ่า เก้า น้ำ", fonts["thai"], sizes["thai"], Vector2(18, 132), Vector2(300, 22), INK)
	add_label("السلام عليكم ١٢٣٤", fonts["arabic"], sizes["arabic"], Vector2(326, 128), Vector2(296, 26), INK, true)
	add_label("ا أ إ آ ٠١٢٣٤٥٦٧٨٩", fonts["arabic"], sizes["arabic"], Vector2(326, 164), Vector2(296, 26), INK, true)
	add_label("SEGMENTED GAME-FONT RUN", fonts["k64f"], sizes["k64f"], Vector2(18, 194), Vector2(604, 18), MUTED)


func draw_small_240(mode: Dictionary) -> void:
	var fonts: Dictionary = mode["fonts"]
	var sizes: Dictionary = mode["sizes"]
	add_rule(10, 32, 300)
	add_rule(10, 146, 300)
	add_label("320x240 -> 640x480", fonts["k64f"], sizes["k64f"], Vector2(10, 8), Vector2(300, 16), INK)
	add_label("K64F HP 0123 / MENU", fonts["k64f"], sizes["k64f"], Vector2(10, 44), Vector2(300, 16), INK)
	add_label("J    こんにちは世界 0123", fonts["j"], sizes["j"], Vector2(10, 68), Vector2(300, 16), INK)
	add_label("CK   ! ！ 漢字 龍龜 你好", fonts["ck"], sizes["ck"], Vector2(10, 92), Vector2(300, 16), INK)
	add_label("TH   กี้ กํ่า เก้า น้ำ", fonts["thai"], sizes["thai"], Vector2(10, 116), Vector2(300, 16), INK)
	add_label("السلام عليكم ١٢٣٤", fonts["arabic"], sizes["arabic"], Vector2(10, 154), Vector2(300, 18), INK, true)
	add_label("ا أ إ آ ٠١٢٣٤٥٦٧٨٩", fonts["arabic"], sizes["arabic"], Vector2(10, 184), Vector2(300, 18), INK, true)


func draw_wide_480(mode: Dictionary) -> void:
	var fonts: Dictionary = mode["fonts"]
	var sizes: Dictionary = mode["sizes"]
	add_rule(24, 64, 592)
	add_rule(24, 246, 592)
	add_label(mode["title"], fonts["k64f"], sizes["k64f"], Vector2(24, 24), Vector2(592, 22), INK)
	add_label("K64F   HP 0123 / MENU / SCORE", fonts["k64f"], sizes["k64f"], Vector2(24, 92), Vector2(592, 24), INK)
	add_label("J      こんにちは世界 0123", fonts["j"], sizes["j"], Vector2(24, 132), Vector2(592, 24), INK)
	add_label("CK     ! ！ 漢字 龍龜 你好 안녕", fonts["ck"], sizes["ck"], Vector2(24, 172), Vector2(592, 24), INK)
	add_label("TH     กี้ กํ่า เก้า น้ำ", fonts["thai"], sizes["thai"], Vector2(24, 212), Vector2(592, 24), INK)
	add_label("السلام عليكم ١٢٣٤", fonts["arabic"], sizes["arabic"], Vector2(24, 282), Vector2(592, 26), INK, true)
	add_label("ا أ إ آ ٠١٢٣٤٥٦٧٨٩", fonts["arabic"], sizes["arabic"], Vector2(24, 334), Vector2(592, 26), INK, true)
	add_label("SQUARE-DOT GAME FONT RENDERING", fonts["k64f"], sizes["k64f"], Vector2(24, 404), Vector2(592, 24), MUTED)


func add_rule(x: int, y: int, width: int) -> void:
	var rule := ColorRect.new()
	rule.color = GUIDE
	rule.position = Vector2(x, y)
	rule.size = Vector2(width, 1)
	_surface_root.add_child(rule)


func add_label(text: String, font_path: String, font_size: int, pos: Vector2, size: Vector2, color: Color, rtl := false) -> void:
	var label := Label.new()
	label.text = text
	label.position = pos
	label.size = size
	label.clip_text = true
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.label_settings = make_label_settings(font_path, font_size, color)
	if rtl:
		label.text_direction = Control.TEXT_DIRECTION_RTL
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	else:
		label.text_direction = Control.TEXT_DIRECTION_LTR
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	_surface_root.add_child(label)


func make_label_settings(font_path: String, font_size: int, color: Color) -> LabelSettings:
	var settings := LabelSettings.new()
	settings.font = load_font(font_path)
	settings.font_size = font_size
	settings.font_color = color
	return settings


func load_font(path: String) -> FontFile:
	if not _font_cache.has(path):
		var font := FontFile.new()
		var error := OK
		if path.get_extension().to_lower() == "fnt":
			error = font.load_bitmap_font(path)
		else:
			error = font.load_dynamic_font(path)
		if error != OK:
			push_error("Failed to load font: %s (%s)" % [path, error])
		font.allow_system_fallback = false
		font.set("antialiasing", 0)
		font.set("hinting", 0)
		font.set("subpixel_positioning", 0)
		font.set("oversampling", 0.0)
		_font_cache[path] = font
	return _font_cache[path]


func make_osd_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = OSD_BG
	style.border_color = Color(0.18, 0.20, 0.22, 0.90)
	style.set_border_width_all(1)
	style.set_corner_radius_all(4)
	style.content_margin_left = 8
	style.content_margin_right = 8
	style.content_margin_top = 4
	style.content_margin_bottom = 4
	return style
