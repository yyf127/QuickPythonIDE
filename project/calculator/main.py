import tkinter as tk

def press(key):
    # 注意：下面所有行都相对于 def 这一行进行了缩进
    current = entry.get()
    if key == "=":
        try:
            result = eval(current)  # 使用局部变量 current 更安全一点
            entry.delete(0, tk.END)
            entry.insert(0, str(result))
        except Exception:
            entry.delete(0, tk.END)
            entry.insert(0, "错误")
    elif key == "C":
        entry.delete(0, tk.END)
    else:
        entry.insert(tk.END, key)

# 主程序部分不需要缩进在函数内，保持顶格写
root = tk.Tk()
root.title("Python 计算器")

# 创建输入框
entry = tk.Entry(root, width=18, font=("Arial", 20), justify="right")
entry.grid(row=0, column=0, columnspan=4, padx=5, pady=5)

#按钮布局
buttons = [
    ["7", "8", "9", "/"],
    ["4", "5", "6", "*"],
    ["1", "2", "3", "-"],
    ["0", ".", "C", "+"],
    ["%", "(", ")", "="],
]

for r, row in enumerate(buttons, start=1):
    for c, text in enumerate(row):
        btn = tk.Button(root, text=text, width=5, height=2,
                        command=lambda t=text: press(t))
        btn.grid(row=r, column=c, padx=2, pady=2)

root.mainloop()
