# IR Storyboard — гайд для аналитика (презентация)

10-слайдовая презентация для аналитиков: что построено и как пользоваться.
Файл: `IR-Storyboard-гайд-аналитика.pptx`.

## Пересобрать
```bash
npm install pptxgenjs react-icons react react-dom sharp
node build.js
```
Рендер в картинки для проверки (нужен LibreOffice):
```bash
soffice --headless --convert-to pdf IR-Storyboard-гайд-аналитика.pptx
pdftoppm -jpeg -r 130 IR-Storyboard-гайд-аналитика.pdf slide
```
