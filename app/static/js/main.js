function selectJoin(flag) {
    document.getElementById("will_join").value = flag ? 1 : 0;

    document.getElementById("joinBtn").classList.toggle("active", flag);
    document.getElementById("noJoinBtn").classList.toggle("active", !flag);

    document.getElementById("formArea").style.display = flag ? "block" : "none";
}

function selectOption(el, name, value) {
    document.querySelectorAll(`[onclick*="${name}"]`).forEach(e => e.classList.remove("active"));
    el.classList.add("active");
    document.querySelector(`input[name=${name}]`).value = value;
}

// 簡易カウントダウン
const timer = document.getElementById("timer");
if (timer) {
    let sec = 86400;
    setInterval(() => {
        sec--;
        let h = Math.floor(sec / 3600);
        let m = Math.floor((sec % 3600) / 60);
        let s = sec % 60;
        timer.textContent = `${h}時間 ${m}分 ${s}秒`;
    }, 1000);
}