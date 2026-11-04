"""Soft multi-label era and region tags from embedding similarity (experimental).

Each tag is a short plain-English description. A question is embedded with the
same local model as the subcategory tagger and scored against every description,
so one question can carry several era or region tags, each with a score.
There are no keyword rules. Nothing here is imported by the app yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

ERAS: dict[str, str] = {
    "Ancient": "prehistory and antiquity: early civilizations, ancient Greece, the Roman Republic and Empire, Persian, Hellenistic, Han and Maurya empires, ancient Egypt and Mesopotamia",
    "Medieval": "late antiquity and the Middle Ages: fall of Rome, Byzantine Empire, rise of Islam, Carolingians, Vikings, crusades, feudalism, Mongol conquests, Black Death, Tang and Song China",
    "Early modern": "1500 to 1789: Renaissance, Reformation, voyages of discovery, Spanish and Ottoman empires, absolutist monarchs, Thirty Years War, scientific revolution, colonial settlement, Mughal and Qing empires, Enlightenment",
    "Revolutionary and industrial age": "1789 to 1870: American, French, Haitian and Latin American revolutions, Napoleon, Industrial Revolution, Victorian era, revolutions of 1848, nationalism and unification, westward expansion, American Civil War",
    "Imperial age and World War I": "1870 to 1920: new imperialism and the scramble for Africa, Meiji Japan, Gilded Age, Belle Epoque, Opium Wars, World War I, Russian Revolution",
    "Interwar and World War II": "1920 to 1945: Roaring Twenties, Great Depression, rise of fascism, Weimar Germany, Stalin, World War II, the Holocaust",
    "Postwar to present": "1945 to today: Cold War, decolonization, Korean and Vietnam wars, civil rights movement, fall of the Soviet Union, globalization, twenty-first century",
}

REGIONS: dict[str, str] = {
    "United States": "United States history, American presidents, Congress, American colonies, Civil War, American West and Native American nations",
    "Canada": "Canada, Canadian provinces, Quebec, the Hudson's Bay Company",
    "Latin America": "Mexico, Central America, Aztec and Maya civilizations, Mexican Revolution, the Caribbean, Cuba, Haiti, Jamaica, plantation slavery, West Indies, Brazil, Portuguese colonial rule, Amazon, Peru, Inca Empire, Chile, Argentina, Colombia, Venezuela, Bolivar, Spanish colonial South America",
    "British Isles": "Britain, England, Scotland, Wales, Ireland, the British monarchy, Parliament, British Empire, London, the Irish famine, Irish independence",
    "France": "France, French kings, the French Revolution, Napoleon, Paris, French colonial empire",
    "Germany and Central Europe": "Germany, Prussia, Austria and the Habsburg monarchy, Holy Roman Empire, Switzerland, Nazi Germany",
    "Italy": "Italy, Italian city-states, papacy, Venice, Florence, Italian unification",
    "Iberia": "Spain, Portugal, the Spanish Empire, Reconquista, Spanish Civil War",
    "Low Countries and Scandinavia": "Netherlands, Belgium, Denmark, Norway, Sweden, Finland, the Dutch Republic, Vikings",
    "Russia and the Soviet Union": "Russia, Russian tsars, Soviet Union, Moscow, Ukraine and Belarus",
    "Eastern Europe and the Balkans": "Poland, Hungary, Czech lands, Romania, Serbia, Yugoslavia, Balkan states",
    "Ancient/Classical Mediterranean": "ancient and classical Greece and Rome: Athens, Sparta, Macedonia, the Aegean, Roman Republic and Empire, Roman emperors and generals, Latin authors, the Mediterranean provinces, Carthage and the Punic Wars",
    "Egypt and North Africa": "ancient and modern Egypt, pharaohs, the Nile, Cairo, Ptolemies, Morocco, Algeria, Tunisia, Libya, the Maghreb",
    "Sub-Saharan Africa": "West, East and Southern Africa: Ghana, Mali, Songhai, Nigeria, Benin, the Sahel, Ethiopia, Kenya, Tanzania, Zulu kingdom, South Africa, Zimbabwe, Congo",
    "Southwest Asia": "Israel, Palestine, Jerusalem, Syria, Lebanon, Jordan, Arabian peninsula, Saudi Arabia, Islamic caliphates, Mesopotamia, Babylon, Assyria, Sumer, Persia, Iran, Achaemenid and Sasanian empires, Ottoman Empire, Turkey, Anatolia, Constantinople and Istanbul, Seljuk Turks",
    "India and South Asia": "India, Mughal Empire, British Raj, Pakistan, Bangladesh, Sri Lanka, Nepal",
    "China": "China, Chinese dynasties, emperors, Communist China, Beijing, Taiwan, Tibet",
    "Japan": "Japan, shoguns, samurai, Meiji restoration, Tokyo, imperial Japan",
    "Korea": "Korea, Korean kingdoms, Joseon dynasty, North and South Korea",
    "Southeast Asia": "Vietnam, Thailand, Cambodia, Burma, Indonesia, Philippines, Malaysia, Singapore",
    "Central Asia and the Steppe": "Central Asia, Mongol Empire, Genghis Khan, Silk Road, Timur, Kazakhstan, Uzbekistan, Afghanistan",
    "Australia and the Pacific": "Australia, New Zealand, Polynesia, Hawaii, Pacific islands, Aboriginal peoples, Maori",
}


# Fitted on weak labels (History subcategory as a rough answer) in development data.
ERA_TEMPERATURE = 0.03
REGION_TEMPERATURE = 0.05


@dataclass(frozen=True, slots=True)
class SoftTag:
    tag: str
    score: float


class SoftTagger:
    """Scores questions against tag descriptions using the cached local embedding model."""

    def __init__(self, vocabulary: dict[str, str], temperature: float = 0.05) -> None:
        from calibration.evaluate_tagger import EmbeddingTagger

        self._embed = EmbeddingTagger._embed
        self.temperature = temperature
        self.tags = list(vocabulary)
        self._matrix = self._embed([f"{tag}: {text}" for tag, text in vocabulary.items()])

    def scores(self, texts: Sequence[str]) -> np.ndarray:
        """Cosine similarity, one row per text and one column per tag."""
        return self._embed(list(texts)) @ self._matrix.T

    def confidences(self, texts: Sequence[str]) -> np.ndarray:
        """Softmax of the scores; each row sums to 1, so confidence is shared between tags."""
        scaled = self.scores(texts) / self.temperature
        scaled -= scaled.max(axis=1, keepdims=True)
        weights = np.exp(scaled)
        return weights / weights.sum(axis=1, keepdims=True)

    def suggest(
        self, texts: Sequence[str], threshold: float = 0.25, limit: int = 3
    ) -> list[list[SoftTag]]:
        """Up to ``limit`` tags per text whose confidence reaches ``threshold``."""
        result = []
        for row in self.confidences(texts):
            order = np.argsort(-row)[:limit]
            result.append([SoftTag(self.tags[i], float(row[i])) for i in order if row[i] >= threshold])
        return result
