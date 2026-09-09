package main

import (
	"fmt"
	"math"
	"unsafe"
)

const hudHeight = 126

type ink struct{ R, G, B byte }

var white = ink{238, 244, 250}
var cyan = ink{102, 223, 227}
var amber = ink{255, 188, 100}

type dib struct {
	dc, bitmap, previous uintptr
	pixels               []byte
	width, height        int
}

func newDIB(width, height int) (*dib, error) {
	d := &dib{width: width, height: height}
	d.dc, _, _ = createCompatibleDC.Call(0)
	info := bitmapInfo{Size: 40, Width: int32(width), Height: -int32(height), Planes: 1, BitCount: 32}
	var address unsafe.Pointer
	d.bitmap, _, _ = createDIBSection.Call(d.dc, uintptr(unsafe.Pointer(&info)), 0, uintptr(unsafe.Pointer(&address)), 0, 0)
	if d.dc == 0 || d.bitmap == 0 {
		d.close()
		return nil, fmt.Errorf("无法创建透明画布")
	}
	d.previous, _, _ = selectObject.Call(d.dc, d.bitmap)
	d.pixels = unsafe.Slice((*byte)(address), width*height*4)
	return d, nil
}
func (d *dib) close() {
	if d.previous != 0 {
		selectObject.Call(d.dc, d.previous)
	}
	if d.bitmap != 0 {
		deleteObject.Call(d.bitmap)
	}
	if d.dc != 0 {
		deleteDC.Call(d.dc)
	}
	d.dc, d.bitmap, d.previous = 0, 0, 0
}

type renderer struct {
	output, mask         *dib
	scale                float64
	width                int
	small, normal, large uintptr
}

func newRenderer(width int, scale float64) (*renderer, error) {
	r := &renderer{width: width, scale: scale}
	var err error
	r.output, err = newDIB(r.px(width), r.px(hudHeight))
	if err != nil {
		return nil, err
	}
	r.mask, err = newDIB(r.px(width), r.px(hudHeight))
	if err != nil {
		r.close()
		return nil, err
	}
	font := func(size, weight int) uintptr {
		f, _, _ := createFont.Call(signed(-int32(r.px(size))), 0, 0, 0, uintptr(weight), 0, 0, 0, 1, 0, 0, 4, 0, uintptr(unsafe.Pointer(wide("Segoe UI"))))
		return f
	}
	r.small, r.normal, r.large = font(12, 400), font(15, 500), font(32, 600)
	if r.small == 0 || r.normal == 0 || r.large == 0 {
		r.close()
		return nil, fmt.Errorf("无法创建系统字体")
	}
	setBkMode.Call(r.mask.dc, 1)
	setTextColor.Call(r.mask.dc, 0xffffff)
	return r, nil
}
func (r *renderer) close() {
	if r.output != nil {
		r.output.close()
	}
	if r.mask != nil {
		r.mask.close()
	}
	for _, f := range []uintptr{r.small, r.normal, r.large} {
		if f != 0 {
			deleteObject.Call(f)
		}
	}
}
func (r *renderer) px(v int) int { return int(math.Round(float64(v) * r.scale)) }
func blend(p []byte, c ink, alpha int) {
	if alpha == 0 {
		return
	}
	inv := 255 - alpha
	p[0] = byte((int(c.B)*alpha + int(p[0])*inv + 127) / 255)
	p[1] = byte((int(c.G)*alpha + int(p[1])*inv + 127) / 255)
	p[2] = byte((int(c.R)*alpha + int(p[2])*inv + 127) / 255)
	p[3] = byte(alpha + (int(p[3])*inv+127)/255)
}
func (r *renderer) pixel(x, y int, color ink, alpha int) {
	if x < 0 || y < 0 || x >= r.output.width || y >= r.output.height {
		return
	}
	i := (y*r.output.width + x) * 4
	blend(r.output.pixels[i:i+4], color, alpha)
}
func (r *renderer) line(x0, y0, x1, y1 int, color ink, alpha int) {
	x0, y0, x1, y1 = r.px(x0), r.px(y0), r.px(x1), r.px(y1)
	dx, dy := abs(x1-x0), -abs(y1-y0)
	sx, sy := -1, -1
	if x0 < x1 {
		sx = 1
	}
	if y0 < y1 {
		sy = 1
	}
	e := dx + dy
	for {
		r.pixel(x0, y0, color, alpha)
		if x0 == x1 && y0 == y1 {
			break
		}
		e2 := 2 * e
		if e2 >= dy {
			e += dy
			x0 += sx
		}
		if e2 <= dx {
			e += dx
			y0 += sy
		}
	}
}
func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
func (r *renderer) label(text string, x, y, width, height int, font uintptr, align uint32) {
	rect := winRect{int32(r.px(x)), int32(r.px(y)), int32(r.px(x + width)), int32(r.px(y + height))}
	old, _, _ := selectObject.Call(r.mask.dc, font)
	drawText.Call(r.mask.dc, uintptr(unsafe.Pointer(wide(text))), signed(-1), uintptr(unsafe.Pointer(&rect)), uintptr(0x20|0x800|0x8000|align)) // single line, no prefix, ellipsis
	selectObject.Call(r.mask.dc, old)
}
func (r *renderer) render(v view, s settings) {
	clear(r.output.pixels)
	clear(r.mask.pixels)
	bg, icons := s.Background*255/100, s.Icons*255/100
	for i := 0; i < len(r.output.pixels); i += 4 {
		blend(r.output.pixels[i:i+4], ink{12, 19, 27}, bg)
	}
	if s.Border {
		for _, l := range [][4]int{{0, 0, r.width - 1, 0}, {0, 0, 0, hudHeight - 1}, {r.width - 1, 0, r.width - 1, hudHeight - 1}, {0, hudHeight - 1, r.width - 1, hudHeight - 1}} {
			r.line(l[0], l[1], l[2], l[3], white, icons/2)
		}
	}
	r.label(v.Remaining, 16, 7, 104, 40, r.large, 0)
	cycle := "周期计时"
	if v.Cycle > 0 {
		cycle = fmt.Sprintf("第 %d 周期", v.Cycle)
	}
	r.label(cycle, 128, 10, 105, 20, r.small, 0)
	r.label(fmt.Sprintf("%d 分钟", s.Minutes), 128, 28, 105, 20, r.small, 0)
	status, detail := v.Status, "右键设置 · 拖动移动"
	if v.Selected != nil {
		detail = fmt.Sprintf("%.1f km  ·  %03.0f°", v.Selected.Distance, v.Selected.Bearing)
	}
	r.label(status, 235, 8, r.width-251, 22, r.normal, 2)
	r.label(detail, 235, 31, r.width-251, 18, r.small, 2)
	if v.Cycle > 0 && v.Progress > 0 {
		r.line(17, 51, 17+int(float64(r.width-34)*v.Progress), 51, white, icons/2)
	}
	center, half := r.width/2, float64(r.width-48)/2
	if v.HasHeading {
		for tick := int(math.Floor((v.Heading-60)/5)) * 5; float64(tick) <= v.Heading+60; tick += 5 {
			x := center + int(math.Round((float64(tick)-v.Heading)*half/60))
			height := 5
			if tick%15 == 0 {
				height = 9
				label := fmt.Sprintf("%03.0f", heading(float64(tick)))
				for cardinal, name := range map[int]string{0: "N", 90: "E", 180: "S", 270: "W"} {
					if int(heading(float64(tick))) == cardinal {
						label = name
					}
				}
				r.label(label, x-20, 60, 40, 17, r.small, 1)
			}
			r.line(x, 82, x, 82+height, white, icons*3/5)
		}
		r.line(center-4, 94, center, 90, white, icons)
		r.line(center, 90, center+4, 94, white, icons)
		for _, t := range v.Targets {
			selected := v.Selected != nil && t.ID == v.Selected.ID
			rel := angle(t.Bearing - v.Heading)
			edge := math.Abs(rel) > 60
			if edge && !t.Friendly && !selected {
				continue
			}
			x := center + int(math.Round(max(-60, min(60, rel))*half/60))
			color := amber
			if t.Friendly {
				color = cyan
			}
			opacity := icons
			if !selected {
				opacity = icons * 3 / 4
			}
			if edge {
				dir := 1
				if rel < 0 {
					dir = -1
				}
				r.line(x-dir*5, 103, x, 108, color, opacity)
				r.line(x, 108, x-dir*5, 113, color, opacity)
			} else if t.Kind == "airfield" {
				r.line(x-4, 101, x-4, 113, color, opacity)
				r.line(x+4, 101, x+4, 113, color, opacity)
				r.line(x-4, 103, x+4, 103, color, opacity)
				r.line(x-4, 111, x+4, 111, color, opacity)
			} else {
				r.line(x, 101, x+6, 107, color, opacity)
				r.line(x+6, 107, x, 113, color, opacity)
				r.line(x, 113, x-6, 107, color, opacity)
				r.line(x-6, 107, x, 101, color, opacity)
			}
			if selected {
				r.line(x-8, 117, x+8, 117, color, icons)
			}
		}
	} else {
		r.label("等待游戏中的飞机位置与航向", 16, 76, r.width-32, 24, r.normal, 1)
	}
	// GDI writes RGB coverage, not reliable alpha. Convert its grayscale mask
	// explicitly so fully transparent backgrounds never create black text boxes.
	gdiFlush.Call()
	for i := 0; i < len(r.mask.pixels); i += 4 {
		coverage := max(r.mask.pixels[i], max(r.mask.pixels[i+1], r.mask.pixels[i+2]))
		blend(r.output.pixels[i:i+4], white, int(coverage)*s.Text/100)
	}
}
func (r *renderer) present(hwnd uintptr) error {
	dc, _, _ := getDC.Call(0)
	defer releaseDC.Call(0, dc)
	size := winSize{int32(r.output.width), int32(r.output.height)}
	origin := winPoint{}
	blendFunction := [4]byte{0, 0, 255, 1}
	ok, _, err := updateLayeredWindow.Call(hwnd, dc, 0, uintptr(unsafe.Pointer(&size)), r.output.dc, uintptr(unsafe.Pointer(&origin)), 0, uintptr(unsafe.Pointer(&blendFunction)), 2)
	if ok == 0 {
		return fmt.Errorf("透明窗口绘制失败: %w", err)
	}
	return nil
}
