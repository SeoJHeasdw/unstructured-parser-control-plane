import Foundation
import CoreGraphics
import CoreText
import ImageIO

struct Block: Decodable {
    let type: String
    let text: String?
    let level: Int?
    let target: String?
    let image: String?
    let caption: String?
    let width: Double?
    let headers: [String]?
    let rows: [[String]]?
    let widths: [Double]?
    let rowHeight: Double?
}
struct Page: Decodable {
    let blocks: [Block]
    let columns: Int
}
struct Job: Decodable {
    let id: String
    let title: String
    let path: String
    let running: String
    let notice: String
    let password: String?
    let pages: [Page]
}

let ink = CGColor(red: 0.12, green: 0.19, blue: 0.23, alpha: 1)
let blue = CGColor(red: 0.12, green: 0.30, blue: 0.38, alpha: 1)
let muted = CGColor(red: 0.27, green: 0.35, blue: 0.39, alpha: 1)
let grid = CGColor(red: 0.77, green: 0.83, blue: 0.86, alpha: 1)
let pale = CGColor(red: 0.93, green: 0.96, blue: 0.97, alpha: 1)
let white = CGColor(gray: 1, alpha: 1)
let pageWidth = 595.28
let pageHeight = 841.89

func attributed(_ text: String, _ size: Double, _ color: CGColor, _ bold: Bool) -> NSAttributedString {
    let name = bold ? "AppleSDGothicNeo-Bold" : "AppleSDGothicNeo-Regular"
    let font = CTFontCreateWithName(name as CFString, size, nil)
    return NSAttributedString(string: text, attributes: [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): color
    ])
}

@discardableResult
func single(_ context: CGContext, _ text: String, _ x: Double, _ y: Double, _ size: Double,
            _ color: CGColor = ink, _ bold: Bool = false, maxWidth: Double? = nil) -> Double {
    var line = CTLineCreateWithAttributedString(attributed(text, size, color, bold))
    var width = CTLineGetTypographicBounds(line, nil, nil, nil)
    if let maximum = maxWidth, width > maximum {
        line = CTLineCreateWithAttributedString(attributed(text, max(4.9, size * maximum / width), color, bold))
        width = CTLineGetTypographicBounds(line, nil, nil, nil)
    }
    context.textPosition = CGPoint(x: x, y: y)
    CTLineDraw(line, context)
    return width
}

func wrap(_ context: CGContext, _ text: String, _ x: Double, _ y: Double, _ width: Double,
          _ size: Double, _ color: CGColor = ink, _ bold: Bool = false) -> Double {
    let paragraph = attributed(text, size, color, bold)
    let typesetter = CTTypesetterCreateWithAttributedString(paragraph)
    var index = 0
    var baseline = y
    while index < paragraph.length {
        let count = max(1, CTTypesetterSuggestLineBreak(typesetter, index, width))
        let line = CTTypesetterCreateLine(typesetter, CFRangeMake(index, count))
        context.textPosition = CGPoint(x: x, y: baseline)
        CTLineDraw(line, context)
        index += count
        baseline -= size * 1.40
    }
    return baseline
}

func table(_ context: CGContext, _ block: Block, _ x: Double, _ y: Double, _ width: Double) -> Double {
    let headers = block.headers!
    let rows = block.rows!
    let weights = block.widths ?? Array(repeating: 1.0, count: headers.count)
    let total = weights.reduce(0, +)
    let columnWidths = weights.map { width * $0 / total }
    let rowHeight = block.rowHeight ?? 18.0
    var top = y + 3
    for (index, row) in ([headers] + rows).enumerated() {
        let height = index == 0 ? min(rowHeight, 23.0) : rowHeight
        let fill = index == 0 ? blue : (index % 2 == 0 ? pale : white)
        context.setFillColor(fill)
        context.fill(CGRect(x: x, y: top - height, width: width, height: height))
        var left = x
        for (column, value) in row.enumerated() {
            let columnWidth = columnWidths[column]
            context.setStrokeColor(grid)
            context.setLineWidth(0.40)
            context.stroke(CGRect(x: left, y: top - height, width: columnWidth, height: height))
            let size = headers.count >= 8 ? 8.0 : 9.1
            single(context, value, left + 5, top - height / 2 - size / 3, size,
                   index == 0 ? white : ink, index == 0, maxWidth: columnWidth - 9)
            left += columnWidth
        }
        top -= height
    }
    return top - 12
}

func putImage(_ context: CGContext, _ block: Block, _ x: Double, _ y: Double,
              _ columnWidth: Double) -> Double {
    let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: block.image!) as CFURL, nil)!
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
    let width = min((block.width ?? 5.5) * 72, columnWidth)
    let height = width * Double(image.height) / Double(image.width)
    context.draw(image, in: CGRect(x: x + (columnWidth - width) / 2,
                                   y: y - height, width: width, height: height))
    if let caption = block.caption {
        single(context, caption, x, y - height - 13, 9.0, muted, maxWidth: columnWidth)
        return y - height - 28
    }
    return y - height - 8
}

var overflow = false

func render(_ job: Job) {
    var media = CGRect(x: 0, y: 0, width: pageWidth, height: pageHeight)
    var attributes: [String: Any] = [
        kCGPDFContextTitle as String: job.title,
        kCGPDFContextAuthor as String: "Fabrikam Bio"
    ]
    if let password = job.password {
        attributes[kCGPDFContextUserPassword as String] = password
        attributes[kCGPDFContextOwnerPassword as String] = "fabrikam-fixture-owner"
    }
    let context = CGContext(URL(fileURLWithPath: job.path) as CFURL,
                            mediaBox: &media, attributes as CFDictionary)!
    for (index, page) in job.pages.enumerated() {
        context.beginPDFPage(nil)
        context.setFillColor(white)
        context.fill(media)
        single(context, job.running, 49, 811, 8.4, muted, maxWidth: 497)
        context.setStrokeColor(grid)
        context.setLineWidth(0.6)
        context.move(to: CGPoint(x: 49, y: 802))
        context.addLine(to: CGPoint(x: 546, y: 802))
        context.strokePath()
        let footer = "대외비 · 가상 문서   |   페이지 \(index + 1) / \(job.pages.count)"
        single(context, footer, 392, 29, 8.4, muted)
        var top = 775.0
        if index == 0 {
            single(context, job.notice, 49, 777, 8.3, muted)
            single(context, job.title, 49, 742, 22.0, ink, true, maxWidth: 497)
            top = 709
        }
        var y = top
        var x = 49.0
        let width = page.columns == 2 ? 238.0 : 497.0
        var footnoteIndex = 0
        let hasFootnote = page.blocks.contains { $0.type == "footnote" }
        for (blockIndex, block) in page.blocks.enumerated() {
            if page.columns == 2 && blockIndex == (page.blocks.count + 1) / 2 {
                x = 308.0
                y = top
            }
            let value = block.text ?? ""
            switch block.type {
            case "heading":
                let size = block.level == 2 ? 12.4 : 15.2
                y = wrap(context, value, x, y - 4, width, size, blue, true) - 5
            case "paragraph", "list":
                let list = block.type == "list"
                if list { single(context, block.level == 2 ? "◦" : "•", x, y, 10.4, blue) }
                y = wrap(context, value, list ? x + 13 : x, y, list ? width - 13 : width, 10.6) - 6
            case "table":
                if !value.isEmpty {
                    single(context, value, x, y, 9.3, blue, true, maxWidth: width)
                    y -= 16
                }
                y = table(context, block, x, y, width)
            case "image":
                y = putImage(context, block, x, y, width)
            case "hyperlink":
                let actualWidth = single(context, value, x, y, 9.3, blue, maxWidth: width)
                if let target = block.target {
                    let escaped = target.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed)
                    if let address = URL(string: escaped ?? target) {
                        context.setURL(address as CFURL, for: CGRect(x: x, y: y - 3, width: actualWidth, height: 13))
                    }
                }
                y -= 17
            case "textbox":
                context.setFillColor(pale)
                context.fill(CGRect(x: x, y: y - 50, width: width, height: 64))
                context.setStrokeColor(grid)
                context.stroke(CGRect(x: x, y: y - 50, width: width, height: 64))
                _ = wrap(context, value, x + 8, y - 7, width - 16, 9.5, blue, true)
                y -= 64
            case "footnote":
                footnoteIndex += 1
                single(context, String(footnoteIndex), min(x + 155, x + width - 10), y + 17, 6.8, blue)
                _ = wrap(context, "\(footnoteIndex)  \(value)", x, 55 - Double(footnoteIndex - 1) * 14,
                         width, 7.8, muted)
            default:
                fatalError("Unknown page block: \(block.type)")
            }
            if y < (hasFootnote ? 76 : 48) {
                if y > -300 {
                    print("\(job.id) page \(index + 1) overflow at \(block.type) \(value.prefix(45)) / \(y)")
                }
                overflow = true
            }
        }
        context.endPDFPage()
    }
    context.closePDF()
}

let input = URL(fileURLWithPath: CommandLine.arguments[1])
let jobs = try JSONDecoder().decode([Job].self, from: Data(contentsOf: input))
for job in jobs { render(job) }

if overflow { exit(2) }
