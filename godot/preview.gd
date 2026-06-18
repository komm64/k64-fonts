extends Control

const INK := Color(0.08, 0.09, 0.10)
const MUTED := Color(0.34, 0.38, 0.42)
const PAPER := Color(1.0, 1.0, 1.0)
const PANEL := Color(0.965, 0.974, 0.974)
const LINE := Color(0.83, 0.86, 0.88)
const ACCENT := Color(0.05, 0.44, 0.41)

var _font_cache := {}


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	RenderingServer.set_default_clear_color(PAPER)

	var scroll := ScrollContainer.new()
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(scroll)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 24)
	margin.add_theme_constant_override("margin_top", 20)
	margin.add_theme_constant_override("margin_right", 24)
	margin.add_theme_constant_override("margin_bottom", 24)
	scroll.add_child(margin)

	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 16)
	root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	margin.add_child(root)

	var title := Label.new()
	title.text = "k64-fonts Godot preview"
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", INK)
	root.add_child(title)

	var note := Label.new()
	note.text = "Rendered through Godot Label nodes from the repository TTF files."
	note.add_theme_font_size_override("font_size", 13)
	note.add_theme_color_override("font_color", MUTED)
	root.add_child(note)

	add_target(root, "640x240 / Reecho game scale", [
		{"label": "K64F", "font": "res://src/komm64Fantasy.ttf", "size": 32, "text": "HP 0123 / MENU / SCORE"},
		{"label": "J", "font": "res://src/JF-Dot-ShinonomeMin16_12px_or1.ttf", "size": 16, "text": "こんにちは世界 0123"},
		{"label": "CK", "font": "res://src/unifont-16px_12px_or1.ttf", "size": 16, "text": "漢字 龍龜 你好 안녕"},
		{"label": "Thai", "font": "res://game/k64-thai-pixel-12w-or12-y1-prop.ttf", "size": 16, "text": "กี้ กํ่า เก้า น้ำ"},
		{"label": "Arabic", "font": "res://game/k64-arabic-sans-medium-pixel-20px-thin-y1.ttf", "size": 20, "text": "السلام عليكم ١٢٣٤", "rtl": true},
		{"label": "Arabic LSB", "font": "res://game/k64-arabic-sans-medium-pixel-20px-thin-y1.ttf", "size": 20, "text": "ا أ إ آ ٠١٢٣٤٥٦٧٨٩", "rtl": true},
	])

	add_target(root, "320x240 square-dot fonts", [
		{"label": "K64F", "font": "res://src/komm64Fantasy.ttf", "size": 16, "text": "HP 0123 / MENU / SCORE"},
		{"label": "J", "font": "res://game/320x240/k64-320-j-shinonome-mincho-12px.ttf", "size": 12, "text": "こんにちは世界 0123"},
		{"label": "CK", "font": "res://game/320x240/k64-320-ck-unifont-12px.ttf", "size": 12, "text": "漢字 龍龜 你好 안녕"},
		{"label": "Thai", "font": "res://game/320x240/k64-320-thai-light-12px-mark16-max2.ttf", "size": 12, "text": "กี้ กํ่า เก้า น้ำ"},
		{"label": "Arabic", "font": "res://game/320x240/k64-320-arabic-light-12px.ttf", "size": 12, "text": "السلام عليكم ١٢٣٤", "rtl": true},
		{"label": "Arabic LSB", "font": "res://game/320x240/k64-320-arabic-light-12px.ttf", "size": 12, "text": "ا أ إ آ ٠١٢٣٤٥٦٧٨٩", "rtl": true},
	])

	add_target(root, "640x480 square-dot fonts", [
		{"label": "K64F", "font": "res://src/komm64Fantasy.ttf", "size": 16, "text": "HP 0123 / MENU / SCORE"},
		{"label": "J", "font": "res://game/640x480/k64-640x480-j-shinonome-mincho-16px.ttf", "size": 16, "text": "こんにちは世界 0123"},
		{"label": "CK", "font": "res://game/640x480/k64-640x480-ck-unifont-16px.ttf", "size": 16, "text": "漢字 龍龜 你好 안녕"},
		{"label": "Thai", "font": "res://game/640x480/k64-640x480-thai-light-16px.ttf", "size": 16, "text": "กี้ กํ่า เก้า น้ำ"},
		{"label": "Arabic", "font": "res://game/640x480/k64-640x480-arabic-light-16px.ttf", "size": 16, "text": "السلام عليكم ١٢٣٤", "rtl": true},
		{"label": "Arabic LSB", "font": "res://game/640x480/k64-640x480-arabic-light-16px.ttf", "size": 16, "text": "ا أ إ آ ٠١٢٣٤٥٦٧٨٩", "rtl": true},
	])


func add_target(parent: VBoxContainer, title_text: String, rows: Array) -> void:
	var card := PanelContainer.new()
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.add_theme_stylebox_override("panel", make_panel_style())
	parent.add_child(card)

	var pad := MarginContainer.new()
	pad.add_theme_constant_override("margin_left", 14)
	pad.add_theme_constant_override("margin_top", 12)
	pad.add_theme_constant_override("margin_right", 14)
	pad.add_theme_constant_override("margin_bottom", 14)
	card.add_child(pad)

	var stack := VBoxContainer.new()
	stack.add_theme_constant_override("separation", 8)
	pad.add_child(stack)

	var heading := Label.new()
	heading.text = title_text
	heading.add_theme_font_size_override("font_size", 15)
	heading.add_theme_color_override("font_color", ACCENT)
	stack.add_child(heading)

	for row in rows:
		add_font_row(stack, row)


func add_font_row(parent: VBoxContainer, row: Dictionary) -> void:
	var line := HBoxContainer.new()
	line.add_theme_constant_override("separation", 12)
	line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(line)

	var label := Label.new()
	label.text = row["label"]
	label.custom_minimum_size = Vector2(110, 0)
	label.add_theme_font_size_override("font_size", 12)
	label.add_theme_color_override("font_color", MUTED)
	line.add_child(label)

	var sample := Label.new()
	sample.text = row["text"]
	sample.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	sample.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	sample.label_settings = make_label_settings(row["font"], int(row["size"]))
	if row.get("rtl", false):
		sample.text_direction = Control.TEXT_DIRECTION_RTL
		sample.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	else:
		sample.text_direction = Control.TEXT_DIRECTION_LTR
	line.add_child(sample)


func make_label_settings(font_path: String, font_size: int) -> LabelSettings:
	var settings := LabelSettings.new()
	settings.font = load_font(font_path)
	settings.font_size = font_size
	settings.font_color = INK
	return settings


func load_font(path: String) -> FontFile:
	if not _font_cache.has(path):
		var font := FontFile.new()
		var error := font.load_dynamic_font(path)
		if error != OK:
			push_error("Failed to load font: %s (%s)" % [path, error])
		_font_cache[path] = font
	return _font_cache[path]


func make_panel_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = PANEL
	style.border_color = LINE
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	return style
