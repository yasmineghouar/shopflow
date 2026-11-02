import time
import threading


class TokenBucket:
    def __init__(self, capacite, debit):
        self.capacite, self.debit = capacite, debit
        self.jetons, self.dernier = float(capacite), time.monotonic()
        self._lock = threading.Lock()

    def autoriser(self, cout=1):
        with self._lock:
            maintenant = time.monotonic()
            ecoule = maintenant - self.dernier

            self.jetons = min(
                self.capacite,
                self.jetons + ecoule * self.debit
            )

            self.dernier = maintenant

            if self.jetons >= cout:
                self.jetons -= cout
                return True

            return False

    def attente(self, cout=1):
        return max(
            0.0,
            (cout - self.jetons) / self.debit
        )


class LoadShedder:
    def __init__(self, max_en_cours, reserve_prioritaire=0.2):
        self.max = max_en_cours
        self.seuil_normal = int(
            max_en_cours * (1 - reserve_prioritaire)
        )
        self.en_cours = 0
        self._lock = threading.Lock()

    def entrer(self, prioritaire=False):
        with self._lock:
            limite = (
                self.max
                if prioritaire
                else self.seuil_normal
            )

            if self.en_cours >= limite:
                return False

            self.en_cours += 1
            return True

    def sortir(self):
        with self._lock:
            self.en_cours -= 1


if __name__ == "__main__":
    seau = TokenBucket(capacite=10, debit=5)
    print("Jetons acceptés :", sum(seau.autoriser() for _ in range(20)))

    shedder = LoadShedder(
        max_en_cours=8,
        reserve_prioritaire=0.25
    )

    admis = [shedder.entrer() for _ in range(7)]
    print("Requêtes normales acceptées :", admis.count(True))
    print("Requête prioritaire acceptée :", shedder.entrer(prioritaire=True))